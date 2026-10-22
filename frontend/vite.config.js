import process from 'node:process'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

const DEFAULT_API_URL = 'http://localhost:8000'

// The API origin the browser may connect to (connect-src), from VITE_API_URL.
function apiOrigin(apiUrl) {
  let url
  try {
    url = new URL(apiUrl)
  } catch {
    throw new Error(`VITE_API_URL is not a valid URL: "${apiUrl}"`)
  }
  if (url.protocol !== 'https:' && url.protocol !== 'http:') {
    throw new Error(`VITE_API_URL must be http(s): "${apiUrl}"`)
  }
  return url.origin
}

// Production Content-Security-Policy (XSS hardening, layer 1). Only for the
// production build: the dev server needs inline scripts for hot reload.
// The QR code on the MFA setup page is a data: PNG drawn by the qrcode library,
// so it needs img-src data: and no inline script.
function contentSecurityPolicy(apiUrl) {
  return {
    'default-src': ["'self'"],
    'script-src': ["'self'"],
    'style-src': ["'self'"],
    'img-src': ["'self'", 'data:'],
    'connect-src': ["'self'", apiOrigin(apiUrl)],
    'object-src': ["'none'"],
    'base-uri': ["'self'"],
    'form-action': ["'self'"],
    'frame-ancestors': ["'none'"],
  }
}

function serialize(policy, { omit = [] } = {}) {
  return Object.entries(policy)
    .filter(([directive]) => !omit.includes(directive))
    .map(([directive, sources]) => `${directive} ${sources.join(' ')}`)
    .join('; ')
}

// Injects the policy into index.html at build time, so it applies on any static
// host. Browsers ignore frame-ancestors in a <meta> tag; it is only enforced as a
// response header (see `preview.headers`, and set the same header on the real host).
function cspMetaTag(policy) {
  return {
    name: 'accessa-csp-meta',
    apply: 'build',
    transformIndexHtml() {
      return [{
        tag: 'meta',
        attrs: { 'http-equiv': 'Content-Security-Policy', content: serialize(policy, { omit: ['frame-ancestors'] }) },
        injectTo: 'head-prepend',
      }]
    },
  }
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const policy = contentSecurityPolicy(env.VITE_API_URL || DEFAULT_API_URL)

  return {
    plugins: [react(), cspMetaTag(policy)],
    // `vite preview` serves the production build: there the full policy is a real
    // response header, including frame-ancestors.
    preview: {
      headers: {
        'Content-Security-Policy': serialize(policy),
        'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'no-referrer',
        'X-Frame-Options': 'DENY',
      },
    },
  }
})

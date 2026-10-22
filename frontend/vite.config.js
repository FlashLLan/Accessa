import process from 'node:process'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { DEFAULT_API_URL, contentSecurityPolicy, serialize } from './csp.config.js'

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
  const apiUrl = env.VITE_API_URL || DEFAULT_API_URL
  const policy = contentSecurityPolicy(apiUrl)

  return {
    plugins: [react(), cspMetaTag(policy)],
    // One value for the API client (src/api/client.js) and the CSP's connect-src.
    define: { 'import.meta.env.VITE_API_URL': JSON.stringify(apiUrl) },
    // `npm test` (Vitest): components rendered in jsdom.
    test: { environment: 'jsdom' },
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

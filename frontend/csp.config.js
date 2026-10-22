// The production Content-Security-Policy, defined once. Used by vite.config.js
// (meta tag in index.html, `vite preview` header) and by scripts/print-csp.js,
// whose output the Caddy server sends as the HTTP header in production.

export const DEFAULT_API_URL = 'http://localhost:8000'

// The API origin the browser may connect to (connect-src), from VITE_API_URL.
export function apiOrigin(apiUrl) {
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

// Only for the production build: the dev server needs inline scripts for hot
// reload. The MFA setup QR code is a data: PNG, so it needs img-src data: and no
// inline script.
export function contentSecurityPolicy(apiUrl) {
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

export function serialize(policy, { omit = [] } = {}) {
  return Object.entries(policy)
    .filter(([directive]) => !omit.includes(directive))
    .map(([directive, sources]) => `${directive} ${sources.join(' ')}`)
    .join('; ')
}

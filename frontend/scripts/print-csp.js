// Prints the production Content-Security-Policy header value for VITE_API_URL
// (the same policy vite.config.js uses). Used by the Dockerfile for Caddy.
import process from 'node:process'
import { DEFAULT_API_URL, contentSecurityPolicy, serialize } from '../csp.config.js'

process.stdout.write(serialize(contentSecurityPolicy(process.env.VITE_API_URL || DEFAULT_API_URL)))

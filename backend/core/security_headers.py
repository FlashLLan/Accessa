"""Security headers on every API response (XSS hardening, layer 1).

The API only ever returns JSON, so its responses get the strictest policy:
nothing may be loaded or executed if a response is ever opened as a document,
and it may not be framed.

Pure ASGI middleware, added as the outermost user middleware, so the headers
are on every response: normal ones, HTTPException/validation/rate-limit errors,
CORS preflight answers, and unhandled errors. Starlette turns unhandled errors
into a 500 *outside* user middleware (without these headers), so this
middleware sends that 500 itself and then re-raises, which keeps the error
logged by the server.

Strict-Transport-Security is sent only in production (APP_ENV=production) and
only for requests that arrived over HTTPS. Behind a reverse proxy that
terminates TLS, run uvicorn with --proxy-headers --forwarded-allow-ips=<proxy>
so the scheme reflects the original request.
"""
import os

API_CSP = "default-src 'none'; frame-ancestors 'none'"
HSTS = "max-age=31536000"

# FastAPI's interactive docs load scripts from a CDN and run inline script, which
# the strict policy blocks. In development they keep the other headers but no
# CSP; in production they get the strict policy like everything else.
DOCS_PATHS = {"/docs", "/docs/oauth2-redirect", "/redoc"}


def _is_production() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() == "production"


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    def _headers(self, scope) -> list[tuple[bytes, bytes]]:
        production = _is_production()
        headers = [
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"no-referrer"),
            (b"x-frame-options", b"DENY"),
        ]
        if production or scope.get("path") not in DOCS_PATHS:
            headers.append((b"content-security-policy", API_CSP.encode()))
        if production and scope.get("scheme") == "https":
            headers.append((b"strict-transport-security", HSTS.encode()))
        return headers

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        security_headers = self._headers(scope)
        names = {name for name, _ in security_headers}
        response_started = False

        async def send_with_headers(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                # Ours replace any same-named header set further in.
                kept = [(k, v) for k, v in message.get("headers", []) if k.lower() not in names]
                message = {**message, "headers": kept + security_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            if not response_started:
                await send_with_headers({
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [(b"content-type", b"application/json")],
                })
                await send_with_headers({
                    "type": "http.response.body",
                    "body": b'{"detail":"Internal Server Error"}',
                })
            raise

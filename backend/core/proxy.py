"""Client address behind a trusted reverse proxy (Railway's edge).

Opt-in with CLIENT_IP_HEADER, e.g. CLIENT_IP_HEADER=X-Real-IP on Railway, whose
edge proxy sets X-Real-IP to the client's remote address and X-Forwarded-Proto
to "https" (docs.railway.com, Public Networking > Specs & Limits).

- The client address (scope["client"], used by the rate limiter and the audit
  log) is taken from that one header only, and only if it is a valid IP
  address; otherwise the TCP peer address is kept.
- X-Forwarded-For is never read: Railway does not document how its edge treats
  a client-supplied X-Forwarded-For, and a client can put anything there.
- X-Forwarded-Proto "https" sets the scheme to https (used for HSTS).
- Without CLIENT_IP_HEADER (local development) nothing is changed, so no
  client-supplied header is ever trusted.

Only enable it where every request reaches the app through the proxy that
overwrites the header: uvicorn must not be reachable directly from the
internet (on Railway only the edge is public). Run uvicorn with
--no-proxy-headers so its own X-Forwarded-For handling stays off.
"""
import ipaddress
import os


class TrustedProxyHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        header = os.getenv("CLIENT_IP_HEADER", "").strip().lower()
        if scope["type"] == "http" and header:
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            scope = dict(scope)
            raw = headers.get(header, "").strip()
            try:
                client_ip = str(ipaddress.ip_address(raw))
            except ValueError:
                client_ip = None
            if client_ip:
                scope["client"] = (client_ip, 0)
            if headers.get("x-forwarded-proto", "").strip().lower() == "https":
                scope["scheme"] = "https"
        await self.app(scope, receive, send)

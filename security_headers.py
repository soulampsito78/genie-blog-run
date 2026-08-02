"""Conservative response headers that do not break the legacy inline admin UI."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware


SECURITY_HEADER_VALUES = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}


def apply_security_headers(response):
    for name, value in SECURITY_HEADER_VALUES.items():
        response.headers.setdefault(name, value)
    return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        return apply_security_headers(response)

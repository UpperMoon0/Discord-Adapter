"""Optional bearer authentication for the MCP ASGI mount."""

from __future__ import annotations

import hmac
import os


class OptionalBearerAuth:
    """
    Protect an ASGI app when MCP_BEARER_TOKEN is configured.

    Leave MCP_BEARER_TOKEN unset only when the endpoint is protected by the
    ChatGPT secure tunnel, a private network, or an authenticating reverse proxy.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        token = os.getenv("MCP_BEARER_TOKEN", "")
        if not token or scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        auth = headers.get("authorization", "")
        expected = f"Bearer {token}"

        if not hmac.compare_digest(auth, expected):
            body = b'{"error":"unauthorized"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        await self.app(scope, receive, send)

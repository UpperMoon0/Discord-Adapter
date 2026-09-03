"""FastAPI route binding for the MCP OAuth manager.

The protocol/state implementation lives in :mod:`utils.mcp_oauth`. FastAPI tries
to derive Pydantic response models from union Response annotations, so this
subclass binds the same handlers with response_model=None explicitly.
"""

from __future__ import annotations

from .mcp_oauth import MCPAuth, MCPOAuthManager as _BaseMCPOAuthManager, OAuthConfig


class MCPOAuthManager(_BaseMCPOAuthManager):
    """MCP OAuth manager with FastAPI response-model inference disabled."""

    def _register_routes(self) -> None:
        route = self.router.add_api_route
        route(
            "/.well-known/oauth-protected-resource",
            self.protected_resource_metadata,
            methods=["GET"],
            response_model=None,
        )
        route(
            "/.well-known/oauth-protected-resource/mcp",
            self.protected_resource_metadata,
            methods=["GET"],
            response_model=None,
        )
        route(
            "/.well-known/oauth-authorization-server",
            self.authorization_server_metadata,
            methods=["GET"],
            response_model=None,
        )
        route(
            "/oauth/register",
            self.register_client,
            methods=["POST"],
            response_model=None,
        )
        route(
            "/oauth/authorize",
            self.authorize_get,
            methods=["GET"],
            response_model=None,
        )
        route(
            "/oauth/authorize",
            self.authorize_post,
            methods=["POST"],
            response_model=None,
        )
        route(
            "/oauth/token",
            self.token,
            methods=["POST"],
            response_model=None,
        )


__all__ = ["MCPAuth", "MCPOAuthManager", "OAuthConfig"]

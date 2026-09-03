"""OAuth 2.0 authorization-code + PKCE protection for the Discord MCP endpoint.

This intentionally mirrors Lily-Shell's owner-approved OAuth model:
- dynamic client registration
- authorization code + PKCE (S256)
- short-lived access tokens and rotating refresh tokens
- protected-resource and authorization-server metadata
- persistent hashed client/token state

The shared owner approval secret is never issued to MCP clients. It is only entered
on the local approval page to authorize a client registration.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import ipaddress
import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

_ALLOWED_SCOPES = {"mcp", "offline_access"}
_ALLOWED_AUTH_METHODS = {"none", "client_secret_basic", "client_secret_post"}
_ALLOWED_GRANTS = {"authorization_code", "refresh_token"}
_ALLOWED_RESPONSES = {"code"}
_CODE_TTL_SECONDS = 5 * 60
_MAX_CLIENTS = 256
_MAX_REGISTRATION_BYTES = 64 * 1024
_DURATION_RE = re.compile(r"^(\d+)(s|m|h|d)?$")
_PKCE_CHALLENGE_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_PKCE_VERIFIER_RE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")


def _token(size: int) -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(size)).rstrip(b"=").decode("ascii")


def _hash(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _parse_duration(raw: str, default_seconds: int) -> int:
    raw = (raw or "").strip()
    if not raw:
        return default_seconds
    match = _DURATION_RE.fullmatch(raw)
    if not match:
        raise ValueError(f"invalid duration {raw!r}; use values such as 1h, 30m, or 720h")
    value = int(match.group(1))
    multiplier = {None: 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]
    seconds = value * multiplier
    if seconds < 60:
        raise ValueError("OAuth token TTL must be at least 60 seconds")
    return seconds


def _validate_https_url(raw: str) -> str:
    raw = raw.strip().rstrip("/")
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("OAuth public URL must be an absolute URL without userinfo or fragment")
    if parsed.scheme == "https":
        return raw
    if parsed.scheme == "http":
        host = parsed.hostname or ""
        try:
            loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost"
        if loopback:
            return raw
    raise ValueError("OAuth public URL must use HTTPS outside loopback development")


def _validate_redirect_uri(raw: str) -> str:
    raw = raw.strip()
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("redirect_uri must be an absolute URL without userinfo or fragment")
    if parsed.scheme == "https":
        return raw
    if parsed.scheme != "http":
        raise ValueError("redirect_uri must use HTTPS, except for loopback clients")
    host = parsed.hostname or ""
    try:
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    if not loopback:
        raise ValueError("HTTP redirect_uri is only allowed for loopback clients")
    return raw


def _normalize_scope(raw: str) -> str:
    parts = raw.split()
    if not parts:
        parts = ["mcp"]
    result: list[str] = []
    seen: set[str] = set()
    for scope in parts:
        if scope not in _ALLOWED_SCOPES:
            raise ValueError(f"unsupported scope {scope!r}")
        if scope not in seen:
            result.append(scope)
            seen.add(scope)
    if "mcp" not in seen:
        result.insert(0, "mcp")
    return " ".join(result)


def _scope_contains(scope: str, wanted: str) -> bool:
    return wanted in scope.split()


def _scope_subset(candidate: str, original: str) -> bool:
    return set(candidate.split()).issubset(set(original.split()))


def _oauth_error(status: int, code: str, description: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": code, "error_description": description},
        headers={"Cache-Control": "no-store"},
    )


@dataclass(slots=True)
class OAuthConfig:
    issuer: str
    resource: str
    owner_token: str
    state_path: str
    access_ttl: int = 3600
    refresh_ttl: int = 30 * 24 * 3600
    server_name: str = "Discord Adapter"

    @classmethod
    def from_env(cls) -> OAuthConfig | None:
        owner_token = os.getenv("MCP_OAUTH_OWNER_TOKEN", "").strip()
        public_url = os.getenv("MCP_PUBLIC_URL", "").strip()
        if not owner_token and not public_url:
            return None
        if not owner_token or not public_url:
            raise ValueError("MCP_OAUTH_OWNER_TOKEN and MCP_PUBLIC_URL must be configured together")
        issuer = _validate_https_url(public_url)
        if len(owner_token) < 32:
            raise ValueError("MCP_OAUTH_OWNER_TOKEN must be at least 32 characters")
        access_ttl = _parse_duration(os.getenv("MCP_OAUTH_ACCESS_TTL", "1h"), 3600)
        refresh_ttl = _parse_duration(os.getenv("MCP_OAUTH_REFRESH_TTL", "720h"), 30 * 24 * 3600)
        if refresh_ttl < access_ttl:
            raise ValueError("MCP_OAUTH_REFRESH_TTL must be at least MCP_OAUTH_ACCESS_TTL")
        state_path = os.getenv("MCP_OAUTH_STATE", "/app/data/oauth-state.json").strip()
        if not state_path:
            raise ValueError("MCP_OAUTH_STATE must not be empty")
        return cls(
            issuer=issuer,
            resource=f"{issuer}/mcp/",
            owner_token=owner_token,
            state_path=state_path,
            access_ttl=access_ttl,
            refresh_ttl=refresh_ttl,
            server_name=os.getenv("MCP_OAUTH_SERVER_NAME", "Discord Adapter").strip() or "Discord Adapter",
        )


class MCPOAuthManager:
    """Small self-hosted OAuth authorization server dedicated to one MCP resource."""

    def __init__(self, config: OAuthConfig):
        config.issuer = _validate_https_url(config.issuer)
        if config.resource != f"{config.issuer}/mcp/":
            raise ValueError("OAuth resource must be the issuer's /mcp/ endpoint")
        if len(config.owner_token.strip()) < 32:
            raise ValueError("OAuth owner token must be at least 32 characters")
        if config.access_ttl < 60 or config.refresh_ttl < config.access_ttl:
            raise ValueError("invalid OAuth token TTLs")
        self.config = config
        self._lock = threading.RLock()
        self._clients: dict[str, dict[str, Any]] = {}
        self._codes: dict[str, dict[str, Any]] = {}
        self._access: dict[str, dict[str, Any]] = {}
        self._refresh: dict[str, dict[str, Any]] = {}
        self.router = APIRouter()
        self._load()
        self._register_routes()

    @classmethod
    def from_env(cls) -> MCPOAuthManager | None:
        config = OAuthConfig.from_env()
        return cls(config) if config else None

    def _register_routes(self) -> None:
        self.router.add_api_route(
            "/.well-known/oauth-protected-resource",
            self.protected_resource_metadata,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/.well-known/oauth-protected-resource/mcp",
            self.protected_resource_metadata,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/.well-known/oauth-authorization-server",
            self.authorization_server_metadata,
            methods=["GET"],
        )
        self.router.add_api_route("/oauth/register", self.register_client, methods=["POST"])
        self.router.add_api_route("/oauth/authorize", self.authorize_get, methods=["GET"])
        self.router.add_api_route("/oauth/authorize", self.authorize_post, methods=["POST"])
        self.router.add_api_route("/oauth/token", self.token, methods=["POST"])

    async def protected_resource_metadata(self) -> JSONResponse:
        return JSONResponse(
            {
                "resource": self.config.resource,
                "authorization_servers": [self.config.issuer],
                "bearer_methods_supported": ["header"],
                "scopes_supported": ["mcp", "offline_access"],
            },
            headers={"Cache-Control": "no-store"},
        )

    async def authorization_server_metadata(self) -> JSONResponse:
        issuer = self.config.issuer
        return JSONResponse(
            {
                "issuer": issuer,
                "authorization_endpoint": f"{issuer}/oauth/authorize",
                "token_endpoint": f"{issuer}/oauth/token",
                "registration_endpoint": f"{issuer}/oauth/register",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": sorted(_ALLOWED_AUTH_METHODS),
                "scopes_supported": ["mcp", "offline_access"],
                "authorization_response_iss_parameter_supported": True,
            },
            headers={"Cache-Control": "no-store"},
        )

    async def register_client(self, request: Request) -> JSONResponse:
        raw = await request.body()
        if len(raw) > _MAX_REGISTRATION_BYTES:
            return _oauth_error(400, "invalid_client_metadata", "client registration document is too large")
        try:
            payload = json.loads(raw or b"{}")
        except (TypeError, ValueError):
            return _oauth_error(400, "invalid_client_metadata", "invalid client registration document")
        if not isinstance(payload, dict):
            return _oauth_error(400, "invalid_client_metadata", "invalid client registration document")

        redirect_uris = payload.get("redirect_uris")
        if not isinstance(redirect_uris, list) or not 1 <= len(redirect_uris) <= 10:
            return _oauth_error(400, "invalid_redirect_uri", "one to ten redirect_uris are required")
        redirects: list[str] = []
        try:
            for raw_redirect in redirect_uris:
                if not isinstance(raw_redirect, str):
                    raise ValueError("redirect_uri must be a string")
                normalized = _validate_redirect_uri(raw_redirect)
                if normalized not in redirects:
                    redirects.append(normalized)
        except ValueError as exc:
            return _oauth_error(400, "invalid_redirect_uri", str(exc))

        grant_types = payload.get("grant_types") or []
        response_types = payload.get("response_types") or []
        if not isinstance(grant_types, list) or not set(grant_types).issubset(_ALLOWED_GRANTS):
            return _oauth_error(400, "invalid_client_metadata", "unsupported grant type")
        if not isinstance(response_types, list) or not set(response_types).issubset(_ALLOWED_RESPONSES):
            return _oauth_error(400, "invalid_client_metadata", "unsupported response type")
        app_type = str(payload.get("application_type") or "").strip()
        if app_type not in {"", "web", "native"}:
            return _oauth_error(400, "invalid_client_metadata", "unsupported application_type")
        auth_method = str(payload.get("token_endpoint_auth_method") or "none").strip()
        if auth_method not in _ALLOWED_AUTH_METHODS:
            return _oauth_error(400, "invalid_client_metadata", "unsupported token_endpoint_auth_method")

        now = int(time.time())
        client_id = f"discord_{_token(24)}"
        client_secret = _token(32) if auth_method != "none" else ""
        client = {
            "id": client_id,
            "secret_hash": _hash(client_secret) if client_secret else "",
            "redirect_uris": redirects,
            "auth_method": auth_method,
            "name": str(payload.get("client_name") or "").strip(),
            "application_type": app_type,
            "registered_at": now,
            "last_used_at": now,
        }
        with self._lock:
            self._cleanup_locked()
            if len(self._clients) >= _MAX_CLIENTS:
                self._evict_oldest_unused_client_locked()
            if len(self._clients) >= _MAX_CLIENTS:
                return _oauth_error(503, "temporarily_unavailable", "client registration capacity reached")
            self._clients[client_id] = client
            try:
                self._save_locked()
            except OSError:
                self._clients.pop(client_id, None)
                return _oauth_error(500, "server_error", "could not persist client")

        response: dict[str, Any] = {
            "client_id": client_id,
            "client_id_issued_at": now,
            "redirect_uris": redirects,
            "token_endpoint_auth_method": auth_method,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "client_name": client["name"],
        }
        if client_secret:
            response["client_secret"] = client_secret
            response["client_secret_expires_at"] = 0
        return JSONResponse(response, status_code=201, headers={"Cache-Control": "no-store"})

    def _parse_authorization_request(self, values: dict[str, str]) -> dict[str, str]:
        if values.get("response_type") != "code":
            raise ValueError("response_type must be code")
        client_id = values.get("client_id", "").strip()
        redirect_uri = values.get("redirect_uri", "").strip()
        challenge = values.get("code_challenge", "").strip()
        resource = values.get("resource", "").strip() or self.config.resource
        if not client_id or not redirect_uri or not challenge:
            raise ValueError("client_id, redirect_uri, and code_challenge are required")
        if values.get("code_challenge_method") != "S256":
            raise ValueError("code_challenge_method must be S256")
        if not _PKCE_CHALLENGE_RE.fullmatch(challenge):
            raise ValueError("invalid S256 code_challenge")
        if resource != self.config.resource:
            raise ValueError("invalid resource")
        scope = _normalize_scope(values.get("scope", ""))
        with self._lock:
            client = self._clients.get(client_id)
            if not client:
                raise ValueError("unknown client_id")
            if redirect_uri not in client["redirect_uris"]:
                raise ValueError("redirect_uri is not registered for this client")
        return {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "resource": resource,
            "state": values.get("state", ""),
            "scope": scope,
            "code_challenge": challenge,
        }

    async def authorize_get(self, request: Request) -> HTMLResponse | JSONResponse:
        values = {key: value for key, value in request.query_params.items()}
        try:
            auth_request = self._parse_authorization_request(values)
        except ValueError as exc:
            return _oauth_error(400, "invalid_request", str(exc))
        return self._render_authorize(auth_request)

    async def authorize_post(self, request: Request) -> HTMLResponse | RedirectResponse | JSONResponse:
        form = await request.form()
        values = {key: str(value) for key, value in form.items()}
        try:
            auth_request = self._parse_authorization_request(values)
        except ValueError as exc:
            return _oauth_error(400, "invalid_request", str(exc))
        provided = values.get("owner_token", "").strip()
        if not _constant_time_equal(provided, self.config.owner_token.strip()):
            return self._render_authorize(auth_request, "The owner token is not valid.", status_code=401)

        code = _token(32)
        now = time.time()
        with self._lock:
            self._cleanup_locked()
            self._codes[_hash(code)] = {
                "client_id": auth_request["client_id"],
                "redirect_uri": auth_request["redirect_uri"],
                "resource": auth_request["resource"],
                "code_challenge": auth_request["code_challenge"],
                "scope": auth_request["scope"],
                "expires_at": now + _CODE_TTL_SECONDS,
            }
            client = self._clients[auth_request["client_id"]]
            client["last_used_at"] = int(now)
            try:
                self._save_locked()
            except OSError:
                return _oauth_error(500, "server_error", "could not persist authorization state")

        callback = urlparse(auth_request["redirect_uri"])
        query = parse_qs(callback.query, keep_blank_values=True)
        query["code"] = [code]
        if auth_request["state"]:
            query["state"] = [auth_request["state"]]
        query["iss"] = [self.config.issuer]
        flattened = [(key, item) for key, values_ in query.items() for item in values_]
        redirect_url = urlunparse(callback._replace(query=urlencode(flattened)))
        return RedirectResponse(redirect_url, status_code=303, headers={"Cache-Control": "no-store"})

    def _render_authorize(
        self,
        auth_request: dict[str, str],
        message: str = "",
        status_code: int = 200,
    ) -> HTMLResponse:
        escaped = {key: html.escape(value, quote=True) for key, value in auth_request.items()}
        message_html = f'<p class="error">{html.escape(message)}</p>' if message else ""
        page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Authorize Discord Adapter</title>
<style>body{{font-family:system-ui,sans-serif;max-width:620px;margin:8vh auto;padding:0 20px;line-height:1.5}}form{{display:grid;gap:14px}}input{{font:inherit;padding:10px}}button{{font:inherit;padding:10px 14px;font-weight:600}}.warn{{padding:12px;border:1px solid #999}}.error{{font-weight:600}}code{{word-break:break-all}}</style></head>
<body><h1>Authorize Discord Adapter</h1><p class="warn">This grants the requesting client access to Discord administration tools for the guilds explicitly allowed by this adapter. Only continue if you initiated this connection.</p>{message_html}<p>Client: <code>{escaped['client_id']}</code></p><form method="post" action="/oauth/authorize">
<input type="hidden" name="response_type" value="code"><input type="hidden" name="client_id" value="{escaped['client_id']}"><input type="hidden" name="redirect_uri" value="{escaped['redirect_uri']}"><input type="hidden" name="resource" value="{escaped['resource']}"><input type="hidden" name="state" value="{escaped['state']}"><input type="hidden" name="scope" value="{escaped['scope']}"><input type="hidden" name="code_challenge" value="{escaped['code_challenge']}"><input type="hidden" name="code_challenge_method" value="S256">
<label>Owner approval token <input type="password" name="owner_token" autocomplete="current-password" required></label><button type="submit">Authorize Discord Adapter</button></form></body></html>"""
        redirect = urlparse(auth_request["redirect_uri"])
        redirect_origin = f"{redirect.scheme}://{redirect.netloc}" if redirect.scheme == "https" else ""
        form_action = "'self'" + (f" {redirect_origin}" if redirect_origin else "")
        headers = {
            "Cache-Control": "no-store",
            "Content-Security-Policy": f"default-src 'none'; style-src 'unsafe-inline'; form-action {form_action}; frame-ancestors 'none'",
            "X-Frame-Options": "DENY",
        }
        return HTMLResponse(page, status_code=status_code, headers=headers)

    async def token(self, request: Request) -> JSONResponse:
        form = await request.form()
        values = {key: str(value) for key, value in form.items()}
        client, auth_error = self._authenticate_client(request, values)
        if auth_error:
            response = _oauth_error(401, "invalid_client", auth_error)
            response.headers["WWW-Authenticate"] = 'Basic realm="discord-adapter-oauth"'
            return response
        grant_type = values.get("grant_type", "")
        if grant_type == "authorization_code":
            return self._exchange_authorization_code(values, client)
        if grant_type == "refresh_token":
            return self._exchange_refresh_token(values, client)
        return _oauth_error(400, "unsupported_grant_type", "grant_type is not supported")

    def _authenticate_client(
        self,
        request: Request,
        values: dict[str, str],
    ) -> tuple[dict[str, Any], str | None]:
        form_id = values.get("client_id", "").strip()
        basic_id = ""
        basic_secret = ""
        has_basic = False
        authorization = request.headers.get("authorization", "")
        if authorization.startswith("Basic "):
            try:
                decoded = base64.b64decode(authorization[6:], validate=True).decode("utf-8")
                basic_id, basic_secret = decoded.split(":", 1)
                has_basic = True
            except (ValueError, UnicodeDecodeError):
                return {}, "invalid HTTP Basic credentials"
        client_id = basic_id if has_basic else form_id
        if not client_id:
            return {}, "client_id is required"
        with self._lock:
            client = self._clients.get(client_id)
            if not client:
                return {}, "unknown client"
            auth_method = client["auth_method"]
            if auth_method == "none":
                if has_basic or values.get("client_secret", ""):
                    return {}, "public client must not send a client secret"
            elif auth_method == "client_secret_basic":
                if not has_basic or not _constant_time_equal(_hash(basic_secret), client["secret_hash"]):
                    return {}, "invalid client credentials"
            elif auth_method == "client_secret_post":
                if has_basic or not _constant_time_equal(_hash(values.get("client_secret", "")), client["secret_hash"]):
                    return {}, "invalid client credentials"
            else:
                return {}, "unsupported client authentication method"
            client["last_used_at"] = int(time.time())
            return dict(client), None

    def _exchange_authorization_code(self, values: dict[str, str], client: dict[str, Any]) -> JSONResponse:
        code = values.get("code", "").strip()
        redirect_uri = values.get("redirect_uri", "").strip()
        verifier = values.get("code_verifier", "").strip()
        resource = values.get("resource", "").strip()
        if not code or not redirect_uri or not verifier or not resource:
            return _oauth_error(400, "invalid_request", "code, redirect_uri, code_verifier, and resource are required")
        if not _PKCE_VERIFIER_RE.fullmatch(verifier):
            return _oauth_error(400, "invalid_grant", "invalid PKCE code_verifier")

        key = _hash(code)
        with self._lock:
            self._cleanup_locked()
            grant = self._codes.pop(key, None)
        if (
            not grant
            or time.time() >= float(grant["expires_at"])
            or grant["client_id"] != client["id"]
            or grant["redirect_uri"] != redirect_uri
        ):
            return _oauth_error(400, "invalid_grant", "authorization code is invalid or expired")
        if not _constant_time_equal(_pkce_challenge(verifier), grant["code_challenge"]):
            return _oauth_error(400, "invalid_grant", "PKCE verification failed")
        if resource != self.config.resource or resource != grant["resource"]:
            return _oauth_error(400, "invalid_target", "resource does not match the authorized MCP server")
        try:
            access, refresh = self._issue_tokens(client["id"], grant["scope"])
        except OSError:
            return _oauth_error(500, "server_error", "could not issue token")
        return JSONResponse(
            {
                "access_token": access,
                "token_type": "Bearer",
                "expires_in": self.config.access_ttl,
                "refresh_token": refresh,
                "scope": grant["scope"],
            },
            headers={"Cache-Control": "no-store"},
        )

    def _exchange_refresh_token(self, values: dict[str, str], client: dict[str, Any]) -> JSONResponse:
        refresh_token = values.get("refresh_token", "").strip()
        if not refresh_token:
            return _oauth_error(400, "invalid_request", "refresh_token is required")
        resource = values.get("resource", "").strip()
        if resource and resource != self.config.resource:
            return _oauth_error(400, "invalid_target", "resource does not match this MCP server")
        key = _hash(refresh_token)
        with self._lock:
            self._cleanup_locked()
            grant = self._refresh.get(key)
            if grant and grant["client_id"] == client["id"] and int(time.time()) < int(grant["expires_at"]):
                self._refresh.pop(key, None)
            else:
                grant = None
        if not grant:
            return _oauth_error(400, "invalid_grant", "refresh token is invalid or expired")

        requested_scope = values.get("scope", "").strip()
        scope = grant["scope"]
        if requested_scope:
            try:
                normalized = _normalize_scope(requested_scope)
            except ValueError:
                return _oauth_error(400, "invalid_scope", "requested scope exceeds the original grant")
            if not _scope_subset(normalized, scope):
                return _oauth_error(400, "invalid_scope", "requested scope exceeds the original grant")
            scope = normalized
        try:
            access, refresh = self._issue_tokens(client["id"], scope)
        except OSError:
            return _oauth_error(500, "server_error", "could not issue token")
        return JSONResponse(
            {
                "access_token": access,
                "token_type": "Bearer",
                "expires_in": self.config.access_ttl,
                "refresh_token": refresh,
                "scope": scope,
            },
            headers={"Cache-Control": "no-store"},
        )

    def _issue_tokens(self, client_id: str, scope: str) -> tuple[str, str]:
        access = _token(32)
        refresh = _token(48)
        now = int(time.time())
        with self._lock:
            self._cleanup_locked()
            self._access[_hash(access)] = {
                "client_id": client_id,
                "scope": scope,
                "expires_at": now + self.config.access_ttl,
            }
            self._refresh[_hash(refresh)] = {
                "client_id": client_id,
                "scope": scope,
                "expires_at": now + self.config.refresh_ttl,
            }
            try:
                self._save_locked()
            except OSError:
                self._access.pop(_hash(access), None)
                self._refresh.pop(_hash(refresh), None)
                raise
        return access, refresh

    def valid_access_token(self, token: str) -> bool:
        if not token:
            return False
        with self._lock:
            self._cleanup_locked()
            grant = self._access.get(_hash(token))
            return bool(
                grant
                and int(time.time()) < int(grant["expires_at"])
                and _scope_contains(grant["scope"], "mcp")
            )

    def unauthorized_response(self) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
        metadata = f"{self.config.issuer}/.well-known/oauth-protected-resource/mcp"
        body = json.dumps(
            {"error": "invalid_token", "error_description": "a valid OAuth access token is required"},
            separators=(",", ":"),
        ).encode("utf-8")
        headers = [
            (b"content-type", b"application/json"),
            (b"cache-control", b"no-store"),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"www-authenticate", f'Bearer resource_metadata="{metadata}", scope="mcp"'.encode("latin-1")),
        ]
        return 401, headers, body

    def _cleanup_locked(self) -> None:
        now = time.time()
        for key, grant in list(self._codes.items()):
            if now >= float(grant["expires_at"]):
                self._codes.pop(key, None)
        for collection in (self._access, self._refresh):
            for key, grant in list(collection.items()):
                if int(now) >= int(grant["expires_at"]):
                    collection.pop(key, None)

    def _client_in_use_locked(self, client_id: str) -> bool:
        now = int(time.time())
        return any(
            grant["client_id"] == client_id and now < int(grant["expires_at"])
            for collection in (self._access, self._refresh)
            for grant in collection.values()
        )

    def _evict_oldest_unused_client_locked(self) -> None:
        for client_id, _client in sorted(self._clients.items(), key=lambda item: int(item[1].get("last_used_at", 0))):
            if not self._client_in_use_locked(client_id):
                self._clients.pop(client_id, None)
                return

    def _load(self) -> None:
        path = Path(self.config.state_path)
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        clients = data.get("clients")
        if isinstance(clients, dict):
            self._clients = clients
        owner_fingerprint = str(data.get("owner_fingerprint") or "")
        current_fingerprint = _hash(self.config.owner_token)
        if not owner_fingerprint or _constant_time_equal(owner_fingerprint, current_fingerprint):
            if isinstance(data.get("access"), dict):
                self._access = data["access"]
            if isinstance(data.get("refresh"), dict):
                self._refresh = data["refresh"]
        self._cleanup_locked()

    def _save_locked(self) -> None:
        path = Path(self.config.state_path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            path.parent.chmod(0o700)
        except OSError:
            pass
        state = {
            "owner_fingerprint": _hash(self.config.owner_token),
            "clients": self._clients,
            "access": self._access,
            "refresh": self._refresh,
        }
        temp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        try:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
            try:
                path.chmod(0o600)
            except OSError:
                pass
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass


class MCPAuth:
    """ASGI auth wrapper: OAuth first, legacy static bearer only as fallback."""

    def __init__(self, app: Any, oauth: MCPOAuthManager | None):
        self.app = app
        self.oauth = oauth

    @property
    def mode(self) -> str:
        if self.oauth:
            return "oauth"
        if os.getenv("MCP_BEARER_TOKEN", "").strip():
            return "bearer"
        return "unconfigured"

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        authorization = headers.get("authorization", "")

        if self.oauth:
            token = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
            if self.oauth.valid_access_token(token):
                await self.app(scope, receive, send)
                return
            status, response_headers, body = self.oauth.unauthorized_response()
            await send({"type": "http.response.start", "status": status, "headers": response_headers})
            await send({"type": "http.response.body", "body": body})
            return

        legacy = os.getenv("MCP_BEARER_TOKEN", "").strip()
        if legacy:
            expected = f"Bearer {legacy}"
            if _constant_time_equal(authorization, expected):
                await self.app(scope, receive, send)
                return
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

        body = b'{"error":"mcp_auth_not_configured"}'
        await send(
            {
                "type": "http.response.start",
                "status": 503,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

import base64
import hashlib
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI
from fastapi.testclient import TestClient

from utils.mcp_oauth_server import MCPAuth, MCPOAuthManager, OAuthConfig


OWNER_TOKEN = "owner-approval-token-0123456789abcdef"
ISSUER = "https://discord.example.test"
RESOURCE = f"{ISSUER}/mcp/"
REDIRECT = "https://chatgpt.example.test/oauth/callback"
VERIFIER = "a" * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()


def make_manager(tmp_path: Path, owner_token: str = OWNER_TOKEN) -> MCPOAuthManager:
    return MCPOAuthManager(
        OAuthConfig(
            issuer=ISSUER,
            resource=RESOURCE,
            owner_token=owner_token,
            state_path=str(tmp_path / "oauth-state.json"),
            access_ttl=3600,
            refresh_ttl=7200,
        )
    )


def make_oauth_client(tmp_path: Path, owner_token: str = OWNER_TOKEN):
    manager = make_manager(tmp_path, owner_token)
    app = FastAPI()
    app.include_router(manager.router)
    return manager, TestClient(app)


def register(client: TestClient) -> dict:
    response = client.post(
        "/oauth/register",
        json={
            "redirect_uris": [REDIRECT],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "client_name": "ChatGPT",
            "application_type": "web",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def authorize(client: TestClient, client_id: str, owner_token: str = OWNER_TOKEN) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "resource": RESOURCE,
        "state": "state-123",
        "scope": "mcp offline_access",
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
    }
    page = client.get("/oauth/authorize", params=params)
    assert page.status_code == 200
    assert "Authorize Discord Adapter" in page.text
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]

    response = client.post(
        "/oauth/authorize",
        data={**params, "owner_token": owner_token},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    callback = urlparse(response.headers["location"])
    query = parse_qs(callback.query)
    assert callback.scheme == "https"
    assert query["state"] == ["state-123"]
    assert query["iss"] == [ISSUER]
    return query["code"][0]


def exchange(client: TestClient, client_id: str, code: str) -> dict:
    response = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": REDIRECT,
            "code_verifier": VERIFIER,
            "resource": RESOURCE,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_metadata_registration_pkce_exchange_and_refresh_rotation(tmp_path):
    manager, client = make_oauth_client(tmp_path)

    protected = client.get("/.well-known/oauth-protected-resource/mcp")
    assert protected.status_code == 200
    assert protected.json()["resource"] == RESOURCE
    assert protected.json()["authorization_servers"] == [ISSUER]

    metadata = client.get("/.well-known/oauth-authorization-server").json()
    assert metadata["authorization_endpoint"] == f"{ISSUER}/oauth/authorize"
    assert metadata["token_endpoint"] == f"{ISSUER}/oauth/token"
    assert metadata["registration_endpoint"] == f"{ISSUER}/oauth/register"
    assert "S256" in metadata["code_challenge_methods_supported"]

    registration = register(client)
    code = authorize(client, registration["client_id"])
    tokens = exchange(client, registration["client_id"], code)
    assert tokens["token_type"] == "Bearer"
    assert tokens["scope"] == "mcp offline_access"
    assert manager.valid_access_token(tokens["access_token"])

    replay = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": registration["client_id"],
            "code": code,
            "redirect_uri": REDIRECT,
            "code_verifier": VERIFIER,
            "resource": RESOURCE,
        },
    )
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"

    refreshed = client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": registration["client_id"],
            "refresh_token": tokens["refresh_token"],
            "resource": RESOURCE,
        },
    )
    assert refreshed.status_code == 200, refreshed.text
    refreshed_tokens = refreshed.json()
    assert refreshed_tokens["refresh_token"] != tokens["refresh_token"]
    assert manager.valid_access_token(refreshed_tokens["access_token"])

    reuse = client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": registration["client_id"],
            "refresh_token": tokens["refresh_token"],
            "resource": RESOURCE,
        },
    )
    assert reuse.status_code == 400
    assert reuse.json()["error"] == "invalid_grant"


def test_owner_approval_and_resource_are_strict(tmp_path):
    _manager, client = make_oauth_client(tmp_path)
    registration = register(client)

    params = {
        "response_type": "code",
        "client_id": registration["client_id"],
        "redirect_uri": REDIRECT,
        "resource": RESOURCE,
        "scope": "mcp",
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
    }
    denied = client.post("/oauth/authorize", data={**params, "owner_token": "wrong"})
    assert denied.status_code == 401
    assert "not valid" in denied.text

    wrong_resource = client.get(
        "/oauth/authorize",
        params={**params, "resource": "https://other.example.test/mcp/"},
    )
    assert wrong_resource.status_code == 400
    assert wrong_resource.json()["error"] == "invalid_request"


def test_state_hashes_secrets_and_owner_rotation_invalidates_grants(tmp_path):
    _manager, client = make_oauth_client(tmp_path)
    registration = register(client)
    code = authorize(client, registration["client_id"])
    tokens = exchange(client, registration["client_id"], code)

    state_path = tmp_path / "oauth-state.json"
    raw_state = state_path.read_text()
    assert OWNER_TOKEN not in raw_state
    assert tokens["access_token"] not in raw_state
    assert tokens["refresh_token"] not in raw_state
    assert (state_path.stat().st_mode & 0o777) == 0o600

    restarted = make_manager(tmp_path)
    assert restarted.valid_access_token(tokens["access_token"])

    rotated_owner = "replacement-owner-token-0123456789abcdef"
    rotated = make_manager(tmp_path, rotated_owner)
    assert not rotated.valid_access_token(tokens["access_token"])
    # Client registrations survive owner-token rotation so ChatGPT can simply
    # re-authorize instead of needing a fresh dynamic registration.
    assert registration["client_id"] in rotated._clients


def test_mcp_auth_wrapper_requires_oauth_and_advertises_resource_metadata(tmp_path):
    manager = make_manager(tmp_path)
    registration_app = FastAPI()
    registration_app.include_router(manager.router)
    oauth_client = TestClient(registration_app)
    registration = register(oauth_client)
    code = authorize(oauth_client, registration["client_id"])
    tokens = exchange(oauth_client, registration["client_id"], code)

    async def protected_app(scope, receive, send):
        body = b"ok"
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain"), (b"content-length", b"2")],
            }
        )
        await send({"type": "http.response.body", "body": body})

    app = FastAPI()
    app.mount("/mcp", MCPAuth(protected_app, manager))
    client = TestClient(app)

    denied = client.get("/mcp/")
    assert denied.status_code == 401
    assert "resource_metadata=" in denied.headers["www-authenticate"]
    assert "/.well-known/oauth-protected-resource/mcp" in denied.headers["www-authenticate"]

    allowed = client.get("/mcp/", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert allowed.status_code == 200
    assert allowed.text == "ok"


def test_unconfigured_mcp_auth_fails_closed(monkeypatch):
    monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)

    async def protected_app(scope, receive, send):
        raise AssertionError("unconfigured auth must not call the protected app")

    app = FastAPI()
    app.mount("/mcp", MCPAuth(protected_app, None))
    response = TestClient(app).get("/mcp/")
    assert response.status_code == 503
    assert response.json()["error"] == "mcp_auth_not_configured"

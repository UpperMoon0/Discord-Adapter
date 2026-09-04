# HTTP API

Discord Adapter deliberately exposes a very small public HTTP surface. Discord administration belongs to authenticated MCP, not to ad-hoc FastAPI control routes.

## Security boundary

The MCP route at `/mcp/` is protected by the configured OAuth flow or the legacy bearer-token fallback. Guild operations are additionally constrained by the Redis-backed MCP guild policy and Discord's own permission hierarchy.

The former unauthenticated `/api/bot`, `/api/cookies`, and `/ws/cookies` surfaces have been removed. The FastAPI OpenAPI/docs routes are disabled as well. Cookie/session material under `/app/data` is host-managed state and is not exposed through HTTP.

## Health and readiness

### `GET /health`

Public liveness endpoint. It intentionally returns operational state without disclosing the MCP guild allowlist, Redis URL, internal Lily-Core URL, bot token, OAuth secrets, or cookie state.

It includes:

- overall healthy/degraded state;
- bot readiness/enabled/startup state;
- addon status;
- MCP auth mode;
- whether the MCP policy is configured and ready;
- policy revision number;
- bounded concurrency statistics.

### `GET /ready`

Readiness-oriented equivalent. Policy-store failure reports `status: degraded`; MCP guild access remains fail-closed.

### `GET /mcp/health`

MCP-specific liveness route inside the authenticated MCP application. It follows the MCP deployment/authentication boundary rather than the public health boundary.

## MCP protocol endpoint

### `/mcp/`

Streamable HTTP MCP endpoint. Use the trailing slash when configuring a client:

```text
https://<adapter-host>/mcp/
```

Authentication mode is selected at process startup:

1. OAuth when both `MCP_PUBLIC_URL` and `MCP_OAUTH_OWNER_TOKEN` are configured;
2. otherwise legacy bearer authentication when `MCP_BEARER_TOKEN` is configured;
3. otherwise fail closed with HTTP 503.

See [MCP tool reference](mcp-tools.md) for the semantic Discord administration operations.

## OAuth endpoints

When OAuth is configured, these routes are registered:

| Route | Purpose |
| --- | --- |
| `GET /.well-known/oauth-protected-resource` | Protected-resource metadata. |
| `GET /.well-known/oauth-protected-resource/mcp` | MCP-specific protected-resource metadata. |
| `GET /.well-known/oauth-authorization-server` | Authorization-server metadata. |
| `POST /oauth/register` | Dynamic OAuth client registration. |
| `GET/POST /oauth/authorize` | Owner-approved authorization flow. |
| `POST /oauth/token` | Authorization-code and refresh-token exchange. |

The implementation supports PKCE S256, authorization-code and refresh-token grants, and the configured MCP scopes.

## Removed legacy routes

The following routes intentionally return 404 and must not be reintroduced as public alternatives to MCP:

```text
/api/bot/*
/api/cookies*
/ws/cookies/*
/docs
/openapi.json
```

If a future internal maintenance workflow needs equivalent functionality, implement it behind a dedicated authenticated/private control plane rather than mounting it on the Internet-facing Adapter application.

## Which interface should automation use?

Use MCP for Discord administration. It provides explicit guild scoping, OAuth/bearer authentication, Redis policy enforcement, semantic tools, Discord permission checks, and destructive-operation annotations.

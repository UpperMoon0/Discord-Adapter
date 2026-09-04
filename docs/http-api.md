# HTTP and WebSocket API

Discord Adapter exposes multiple HTTP surfaces from the same FastAPI process. They do **not** all share the same authentication boundary.

## Security boundary

The MCP route at `/mcp/` is protected by the configured MCP OAuth flow or the legacy bearer-token fallback, and guild operations are additionally constrained by the Redis-backed guild policy.

The legacy `/api/bot`, `/api/cookies`, and `/ws/cookies` routes are mounted directly on FastAPI and do **not** inherit MCP OAuth or the MCP guild allowlist. Treat them as private/internal management APIs. Do not expose them to an untrusted network unless an authenticated reverse proxy or equivalent control protects them.

The cookie routes are especially sensitive because they can read, download, overwrite, or stream `/app/data/cookies.txt`.

## Health and readiness

### `GET /health`

Returns overall service health. The top-level status is `healthy` when the policy store is ready and `degraded` otherwise.

The response includes:

- Discord bot readiness/enabled/startup state;
- Lily-Core availability;
- whether a Discord token is configured;
- addon status (`enabled`, `strict`, `load_attempted`, `loaded`, `failed`);
- MCP auth mode;
- Redis policy configured/readiness state and the complete current policy status;
- concurrency statistics.

### `GET /ready`

Returns readiness-focused state. Policy-store failure reports `status: degraded`. The response also includes bot, Lily-Core, addon, and concurrency state.

A degraded policy store is intentionally fail-closed for MCP guild administration.

### `GET /mcp/health`

MCP-specific liveness route mounted inside the MCP application. It returns:

- `status` and service identity;
- active guild-policy status;
- whether the legacy `MCP_BEARER_TOKEN` is configured.

This route belongs to the mounted MCP application; use the same deployment assumptions as the MCP surface.

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

See [MCP tool reference](mcp-tools.md) for the semantic Discord operations behind this endpoint.

## OAuth endpoints

When OAuth is configured, the following routes are registered:

| Route | Purpose |
| --- | --- |
| `GET /.well-known/oauth-protected-resource` | Protected-resource metadata. |
| `GET /.well-known/oauth-protected-resource/mcp` | MCP-specific protected-resource metadata. |
| `GET /.well-known/oauth-authorization-server` | Authorization-server metadata. |
| `POST /oauth/register` | Dynamic OAuth client registration. |
| `GET/POST /oauth/authorize` | Owner-approved authorization flow. |
| `POST /oauth/token` | Authorization-code and refresh-token exchange. |

The implementation supports PKCE S256, authorization-code and refresh-token grants, `mcp`/`offline_access` scopes, and client authentication methods supported by the OAuth implementation.

`MCP_OAUTH_OWNER_TOKEN` is entered only for owner approval; it is not handed to the MCP client as an access token.

## Legacy bot-control API

Prefix: `/api/bot`

These routes operate directly on the bot service and are not constrained by the MCP Redis guild policy.

### `POST /api/bot/enable`

Enables bot execution when a Discord bot token is configured.

### `POST /api/bot/disable`

Disables/stops bot execution.

### `GET /api/bot/status`

Returns current bot state.

### `POST /api/bot/send-message`

Sends a message directly to a Discord channel as the bot.

JSON request:

```json
{
  "channel_id": 123456789012345678,
  "message": "hello"
}
```

`message` is limited to 1–2000 characters by the request model.

This legacy route does not provide the MCP tool's explicit mention/reply/quote controls and does not inherit the MCP guild allowlist. Prefer `discord_send_message` for ChatGPT/MCP administration.

### `GET /api/bot/channels`

Lists available text channels. Optional query parameter:

```text
guild_id=<discord guild id>
```

When omitted, the bot service may return channels across all guilds it can see.

### `GET /api/bot/guilds`

Lists guilds the bot is currently in.

This is bot membership discovery, not MCP-policy discovery. For MCP use, call `discord_list_servers`, which filters to policy-allowed guilds.

## Cookie-management API

Persistent cookie path:

```text
/app/data/cookies.txt
```

Prefix: `/api/cookies`

### `GET /api/cookies`

Without query parameters, returns whether the cookie file exists and its path without returning content.

Supported query parameters:

- `include_content` — when true, include a text slice;
- `offset` — character offset, default `0`;
- `limit` — maximum returned character count, default `50000`.

Example:

```text
GET /api/cookies?include_content=true&offset=0&limit=50000
```

The response may include cookie contents and must be treated as secret-bearing data.

### `GET /api/cookies/download`

Downloads the entire cookie file as `cookies.txt`. Returns 404 when the file does not exist.

### `POST /api/cookies`

Multipart file upload that overwrites `/app/data/cookies.txt`.

Form field:

```text
file=<uploaded cookies.txt>
```

The route creates the persistent data directory when necessary.

## Cookie WebSocket

### `WS /ws/cookies/`

After connecting, send the text message:

```text
get
```

The server streams the cookie file as text chunks and closes the socket when complete.

No other command is implemented by this WebSocket handler.

## OpenAPI developer UI

Because the process is a normal FastAPI application, the standard FastAPI OpenAPI endpoints are available unless disabled by an outer deployment layer:

- `/docs`
- `/openapi.json`

Use these only on a trusted management surface; the presence of interactive docs does not add authentication to the legacy routes.

## Which interface should new automation use?

For Discord administration, use MCP. It has explicit guild scoping, OAuth/bearer authentication, Redis policy enforcement, semantic tools, Discord permission checks, and destructive-operation annotations.

Keep `/api/bot` and the cookie routes for compatibility with trusted deployment components that specifically need them. They should not be treated as an alternative public admin API.

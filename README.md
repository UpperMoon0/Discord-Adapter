# Discord Adapter

Discord bot adapter for Lily-Core. The service connects Discord to Lily-Core and exposes a guild-scoped Model Context Protocol (MCP) administration endpoint for ChatGPT.

## Features

- Discord bot integration with Lily-Core
- FastAPI health/readiness endpoints
- Streamable HTTP MCP endpoint at `/mcp/`
- Self-hosted OAuth 2.0 authorization-code + PKCE flow
- Semantic Discord administration tools instead of a raw REST proxy
- Redis-backed runtime guild access policy with an immutable in-memory snapshot
- One-time migration/bootstrap from `DISCORD_ADMIN_GUILD_IDS`
- Deployment-gated runtime policy writes, disabled by default
- Bounded Redis audit history for policy mutations
- Cross-event-loop dispatch so MCP requests execute Discord operations on the bot's owning event loop

## Setup

### Prerequisites

- Python 3.11+
- Discord bot token
- Redis 7+ for the MCP guild policy
- Access to Lily-Core / Consul when chat integration is enabled
- Optional Discord **Server Members Intent** for reliable name-based member search

### Environment variables

Create a `.env` file based on `.env.template`.

```env
DISCORD_BOT_TOKEN=your_discord_bot_token_here

# One-time policy bootstrap only. Redis becomes authoritative after the first seed.
DISCORD_ADMIN_GUILD_IDS=123456789012345678,234567890123456789

# Runtime policy store.
REDIS_URL=redis://redis:6379/0

# Privileged policy mutations are denied unless explicitly enabled by deployment.
MCP_POLICY_WRITES_ENABLED=false
DISCORD_POLICY_REDIS_KEY=lily:discord-adapter:access-policy:v1
DISCORD_POLICY_AUDIT_REDIS_KEY=lily:discord-adapter:access-policy:audit:v1
DISCORD_POLICY_AUDIT_MAX_ENTRIES=100

DISCORD_MEMBERS_INTENT=false

MCP_PUBLIC_URL=https://lily-discord-adapter.nstut.cloud
MCP_OAUTH_OWNER_TOKEN=at-least-32-characters
MCP_OAUTH_STATE=/app/data/oauth-state.json
MCP_OAUTH_ACCESS_TTL=1h
MCP_OAUTH_REFRESH_TTL=720h
MCP_OAUTH_SERVER_NAME=Discord Adapter

# Legacy compatibility only. OAuth takes precedence when configured.
MCP_BEARER_TOKEN=

MCP_ALLOWED_HOSTS=
MCP_ALLOWED_ORIGINS=
PORT=8004
CONSUL_HTTP_ADDR=consul:8500
```

## Runtime guild access policy

The adapter no longer treats `DISCORD_ADMIN_GUILD_IDS` as the live policy. Redis is authoritative after startup migration.

Startup behavior:

1. Connect to `REDIS_URL` before MCP administration is considered ready.
2. If a valid policy already exists in Redis, load it and ignore later environment changes.
3. If Redis has no policy, parse `DISCORD_ADMIN_GUILD_IDS` once and persist that value into Redis.
4. If neither Redis nor a valid bootstrap policy is available, deny all guilds.

The stored model is capability-ready rather than a bare set. A guild entry is represented as an object with `allowed: true` and a `capabilities` list, so future per-capability enforcement can be added without replacing the key format.

Guild checks use an immutable in-memory snapshot and do not perform Redis I/O on Discord request paths. Runtime mutations execute Redis writes first and only swap the snapshot after the Redis transaction succeeds. A Redis write failure therefore leaves the previous active policy intact.

### Policy MCP tools

Read/reload tools:

- `discord_get_access_policy`
- `discord_reload_access_policy`

Privileged mutation tools:

- `discord_policy_allow_guild`
- `discord_policy_remove_guild`

Policy mutation tools are unavailable in practice unless the deployment explicitly sets:

```env
MCP_POLICY_WRITES_ENABLED=true
```

The default is `false`. Ordinary Discord administration access alone is not enough to expand the guild allowlist.

Every successful policy mutation is written to a bounded Redis audit list with the action, guild ID, UTC timestamp, previous state, new state, and available caller/tool context. `DISCORD_POLICY_AUDIT_MAX_ENTRIES` defaults to 100 and is bounded by the service.

`discord_get_access_policy`, `/health`, `/ready`, and the MCP health route expose policy-store state including Redis configuration/availability, configured state, `all_guilds`, guild IDs, policy version/revision, source, and whether policy writes are enabled.

## OAuth / MCP

The Streamable HTTP MCP endpoint is:

```text
https://<adapter-host>/mcp/
```

Use the trailing slash. Public deployments should use the built-in OAuth flow. The adapter exposes protected-resource metadata, authorization-server metadata, dynamic client registration, owner approval, authorization-code exchange with PKCE S256, and refresh-token rotation.

OAuth endpoints:

```text
/.well-known/oauth-protected-resource
/.well-known/oauth-protected-resource/mcp
/.well-known/oauth-authorization-server
/oauth/register
/oauth/authorize
/oauth/token
```

`MCP_OAUTH_OWNER_TOKEN` is an owner-approval secret, not a bearer token shared with ChatGPT. Dynamic client registrations and hashed access/refresh grants are persisted in `MCP_OAUTH_STATE` on the persistent `/app/data` volume.

If OAuth is not configured, `MCP_BEARER_TOKEN` remains a legacy fallback. If neither is configured, `/mcp/` fails closed.

The MCP SDK also validates HTTP `Host` to prevent DNS rebinding. When `MCP_ALLOWED_HOSTS` is empty, localhost plus `lily-discord-adapter.<DOMAIN_NAME>` are derived automatically.

## Discord administration model

Every guild-scoped operation requires an explicit `guild_id`, except initial server/policy discovery. There is no bulk destructive endpoint; multi-guild operations require one explicit call per guild.

The main discovery tool is `discord_list_servers`, which returns only policy-allowed guilds and reports the bot's permission/capability matrix.

The administration surface covers:

- channels and messages
- members, moderation, roles, and nicknames
- channel permission overwrites
- server settings
- webhooks
- emoji and stickers
- invites and threads
- voice state/movement
- Discord audit-log reads

Messages sent through MCP disable Discord mentions by default, preventing accidental `@everyone`, `@here`, user, or role pings.

MCP does not bypass Discord permissions or role hierarchy. Prefer granting only the Discord permissions the bot actually needs instead of `Administrator`.

For reliable member discovery by name, enable **Server Members Intent** in the Discord Developer Portal and set:

```env
DISCORD_MEMBERS_INTENT=true
```

Exact user-ID operations can still work without the privileged intent.

## Health and readiness

`GET /health` and `GET /ready` include policy-store readiness. A missing/unreachable Redis store degrades policy readiness and guild access remains fail-closed.

The MCP-specific health route also returns the active guild policy status.

## Installation

```bash
pip install -r requirements.txt
python main.py
```

### Docker

```bash
docker build -t nstut/lily-discord-adapter .

docker run -d \
  --name lily-discord-adapter \
  --network nstut-network \
  -p 8004:8004 \
  -e DISCORD_BOT_TOKEN=your_token \
  -e REDIS_URL=redis://redis:6379/0 \
  -e MCP_POLICY_WRITES_ENABLED=false \
  -e DOMAIN_NAME=nstut.cloud \
  -e MCP_PUBLIC_URL=https://lily-discord-adapter.nstut.cloud \
  -e MCP_OAUTH_OWNER_TOKEN=your_owner_approval_token \
  -e CONSUL_HTTP_ADDR=consul:8500 \
  nstut/lily-discord-adapter
```

Production build/publish/deploy is owned by `UpperMoon0/NsTut-CICD`, not by this repository's source CI workflow.

## Existing HTTP API

The existing bot-control routes remain under `/api/bot`. The MCP administration surface is separate and enforces the Redis-backed guild policy.

## Bot commands

- `!ping` - Check if the bot is alive
- `!lily <message>` - Send a message to Lily-Core
- `!join` - Join your voice channel
- `!leave` - Leave the current voice channel

## Architecture

```text
                         ChatGPT / MCP client
                                  |
                         OAuth + Streamable HTTP
                                  v
┌─────────────┐     ┌─────────────────────────┐     ┌─────────────┐
│   Discord   │<--->│     Discord Adapter     │<--->│  Lily-Core  │
│   Servers   │     │  FastAPI + MCP + bot    │     │             │
└─────────────┘     └─────────────────────────┘     └─────────────┘
                              |        |
                              |        v
                              |    ┌─────────┐
                              |    │  Redis  │ policy + audit
                              |    └─────────┘
                              v
                         ┌─────────────┐
                         │   Consul    │
                         └─────────────┘
```

MCP administration is constrained by four layers:

1. MCP OAuth/bearer authentication.
2. Deployment-level policy-write capability for allowlist mutations.
3. Redis-backed guild access policy.
4. Discord bot permissions and role hierarchy inside each guild.

## Testing

Source CI builds the Docker image, runs Python syntax compilation, executes the full pytest suite, starts a Redis sidecar, launches the adapter container with `REDIS_URL`, and requires `/health` to report `mcp_policy_store_ready=true`.

Policy tests cover empty Redis fail-closed behavior, one-time env bootstrap, Redis authority over later env changes, runtime allow/remove, reload, atomic snapshot preservation on Redis failures, default-disabled policy writes, status output, bounded audit persistence, MCP tool advertisement, and existing guild-scoped protection behavior.

# Discord Adapter

Discord Adapter connects Discord to Lily-Core and exposes a guild-scoped Model Context Protocol (MCP) administration surface for ChatGPT and other MCP clients.

The repository currently contains three distinct runtime surfaces:

- the Discord bot and Lily-Core session bridge;
- the authenticated MCP administration endpoint at `/mcp/`;
- legacy/internal FastAPI and cookie-management endpoints used by the surrounding deployment.

Do not assume those surfaces share authentication. MCP OAuth and the Redis guild policy protect the MCP administration surface; the legacy `/api/bot`, `/api/cookies`, and `/ws/cookies` routes are separate and should remain on a trusted network unless another gateway protects them.

## Features

- Discord bot integration with Lily-Core
- FastAPI health/readiness endpoints
- Streamable HTTP MCP endpoint at `/mcp/`
- 60 semantic Discord administration MCP tools
- Self-hosted OAuth 2.0 authorization-code + PKCE flow
- Redis-backed runtime guild access policy with an immutable in-memory snapshot
- One-time migration/bootstrap from `DISCORD_ADMIN_GUILD_IDS`
- Deployment-gated runtime policy writes, disabled by default
- Bounded Redis audit history for policy mutations
- Read-only inspection of images, GIFs, and videos attached to Discord messages
- Explicit user/role mentions, replies, and quotes for MCP-sent messages
- Independently packaged Discord addons through Python entry points
- Cross-event-loop dispatch so MCP requests execute Discord operations on the bot's owning event loop

## Documentation

- [Configuration](docs/configuration.md) — every runtime environment variable and fail-closed behavior
- [MCP tool reference](docs/mcp-tools.md) — complete 60-tool inventory and important semantics
- [HTTP and WebSocket API](docs/http-api.md) — health, OAuth, legacy bot-control, and cookie routes
- [Addon development](docs/addons.md) — stable addon contract, lifecycle, configuration, and deployment

## Prerequisites

- Python 3.11+
- Discord bot token when Discord bot features are enabled
- Discord **Message Content Intent** enabled in the Developer Portal for Lily-Core text-session behavior
- Optional Discord **Server Members Intent** for reliable name-based member search
- Redis 7+ for the MCP guild policy
- Access to Lily-Core / Consul when chat integration is enabled
- `ffmpeg`/`ffprobe` for GIF/video MCP inspection and voice/media functionality; the Docker image installs `ffmpeg`

## Quick start

Create a `.env` from `.env.template`. A minimal MCP-capable local configuration looks like:

```env
DISCORD_BOT_TOKEN=your_discord_bot_token_here
REDIS_URL=redis://redis:6379/0
DISCORD_ADMIN_GUILD_IDS=123456789012345678

MCP_PUBLIC_URL=https://lily-discord-adapter.example.com
MCP_OAUTH_OWNER_TOKEN=replace-with-at-least-32-random-characters
MCP_POLICY_WRITES_ENABLED=false
```

Then run:

```bash
pip install -r requirements.txt
python main.py
```

The HTTP service listens on `PORT` (default `8004`). The MCP endpoint uses the trailing slash:

```text
https://<adapter-host>/mcp/
```

See [configuration](docs/configuration.md) before production deployment; the example above intentionally omits tuning, addon, media, and advanced OAuth settings.

### Docker

```bash
docker build -t nstut/discord-adapter .

docker run -d \
  --name discord-adapter \
  --network nstut-network \
  -p 8004:8004 \
  -e DISCORD_BOT_TOKEN=your_token \
  -e REDIS_URL=redis://redis:6379/0 \
  -e MCP_POLICY_WRITES_ENABLED=false \
  -e DOMAIN_NAME=nstut.cloud \
  -e MCP_PUBLIC_URL=https://lily-discord-adapter.nstut.cloud \
  -e MCP_OAUTH_OWNER_TOKEN=your_owner_approval_token \
  -e CONSUL_HTTP_ADDR=consul:8500 \
  nstut/discord-adapter
```

Production build/publish/deploy is owned by `UpperMoon0/NsTut-CICD`, not by this repository's source CI workflow.

## Runtime guild access policy

`DISCORD_ADMIN_GUILD_IDS` is a one-time bootstrap source, not the live policy. Redis becomes authoritative after the first successful seed.

Startup behavior:

1. Connect to `REDIS_URL` before MCP administration is considered ready.
2. If a valid policy already exists in Redis, load it and ignore later bootstrap-environment changes.
3. If Redis has no policy, parse `DISCORD_ADMIN_GUILD_IDS` once and persist that value into Redis.
4. If neither Redis nor a valid bootstrap policy is available, deny all guilds.

`DISCORD_ADMIN_GUILD_IDS=*` is supported only as an intentional bootstrap to all guilds. Prefer explicit guild IDs.

The stored model is capability-ready rather than a bare set. A guild entry is represented with `allowed: true` plus a `capabilities` list so future per-capability enforcement can be added without replacing the key format.

Guild checks use an immutable in-memory snapshot and do not perform Redis I/O on Discord request paths. Runtime mutations write Redis first and only swap the active snapshot after the transaction succeeds. A Redis write failure therefore leaves the previous active policy intact.

### Policy MCP tools

Read/reload tools:

- `discord_get_access_policy`
- `discord_reload_access_policy`

Privileged mutation tools:

- `discord_policy_allow_guild`
- `discord_policy_remove_guild`

Policy mutation tools require:

```env
MCP_POLICY_WRITES_ENABLED=true
```

The default is `false`. Ordinary Discord administration access is intentionally insufficient to expand the guild allowlist.

Every successful policy mutation is written to a bounded Redis audit list with the action, guild ID, UTC timestamp, previous state, new state, and available caller/tool context. `DISCORD_POLICY_AUDIT_MAX_ENTRIES` defaults to `100`.

`discord_get_access_policy`, `/health`, `/ready`, and `/mcp/health` expose policy-store state including Redis readiness, configured state, `all_guilds`, guild IDs, policy version/revision, source, and whether policy writes are enabled.

## OAuth / MCP

Public deployments should use the built-in OAuth flow. OAuth is enabled only when **both** `MCP_PUBLIC_URL` and `MCP_OAUTH_OWNER_TOKEN` are configured. Configuring only one is an error.

OAuth endpoints:

```text
/.well-known/oauth-protected-resource
/.well-known/oauth-protected-resource/mcp
/.well-known/oauth-authorization-server
/oauth/register
/oauth/authorize
/oauth/token
```

The implementation supports dynamic client registration, authorization-code flow, PKCE S256, the `mcp` and `offline_access` scopes, short-lived access tokens, and rotating refresh tokens.

`MCP_OAUTH_OWNER_TOKEN` is an owner-approval secret, not a bearer token shared with ChatGPT. Dynamic client registrations and hashed access/refresh grants are persisted in `MCP_OAUTH_STATE`, which defaults to `/app/data/oauth-state.json`.

If OAuth is not configured, `MCP_BEARER_TOKEN` remains a legacy fallback. If neither OAuth nor the bearer token is configured, `/mcp/` fails closed with HTTP 503.

The MCP SDK validates HTTP `Host` to reduce DNS-rebinding risk. When `MCP_ALLOWED_HOSTS` is empty, localhost is allowed and `lily-discord-adapter.<DOMAIN_NAME>` is derived when `DOMAIN_NAME` is configured.

## Discord administration model

Every guild-scoped MCP operation requires an explicit `guild_id`, except initial server/policy discovery. There is no multi-guild destructive endpoint; apply an action to multiple guilds with separate explicit calls.

`discord_list_servers` is the primary discovery tool. It returns only policy-allowed guilds and includes the bot's available permission/capability matrix for each server.

The MCP surface covers:

- server, channel, role, member, and permission management;
- message reads/writes, explicit mentions, replies, quotes, pins, and filtered purge;
- moderation, bans, timeouts, nicknames, and voice-state operations;
- webhooks, emoji, stickers, invites, and threads;
- Discord audit-log reads;
- visual inspection of message images, GIFs, and videos;
- Redis-backed guild-policy inspection and privileged mutation.

Messages sent through MCP suppress Discord mentions by default. `discord_send_message` can explicitly ping selected users or roles with `mention_user_ids` / `mention_role_ids`, reply with `reply_to_message_id`, or quote with `quote_message_id`. `@everyone` and `@here` are never enabled. Replies do not automatically ping the referenced author unless that user is explicitly selected.

`discord_read_messages` returns jump URLs and reply/reference metadata. Use `discord_list_message_media` followed by `discord_read_message_media` to inspect visual attachments or embeds. GIFs and videos are sampled into representative frames.

MCP does not bypass Discord permissions or role hierarchy. Grant only the Discord permissions the bot needs rather than `Administrator` where practical.

See the [complete MCP tool reference](docs/mcp-tools.md) for every tool name and operation class.

## Discord bot behavior

The bot has two user-facing behaviors.

### Lily-Core chat sessions

Ordinary non-command messages are considered for Lily-Core chat handling. A user starts a session with a message beginning with `Hey Lily` and ends it with exactly `Goodbye Lily`. While a session is active, messages are queued to Lily-Core; supported audio attachments (`.wav`, `.mp3`, `.m4a`, `.flac`, `.ogg`) are forwarded as audio attachment metadata.

This flow requires Discord Message Content Intent because the adapter reads normal message text.

### Slash commands

The currently registered application commands are:

- `/join` — join the invoking user's voice channel
- `/play <url>` — queue a YouTube URL
- `/skip` — skip the current track

The old prefix-command list (`!ping`, `!lily`, `!join`, `!leave`) is not part of the current command controller and should not be relied on.

For name-based MCP member discovery, enable **Server Members Intent** in the Discord Developer Portal and set:

```env
DISCORD_MEMBERS_INTENT=true
```

Exact user-ID operations can still work without that privileged intent.

## Addons

Discord Adapter can load independently packaged addons from the `discord_adapter.addons` Python entry-point group. Addons are opt-in through `DISCORD_ADDONS`; failures are isolated by default and become startup-fatal only with `DISCORD_ADDON_STRICT=true`.

See [docs/addons.md](docs/addons.md) for the supported public contract and lifecycle.

## Health and readiness

- `GET /health` returns overall adapter health, bot/Lily-Core state, addon status, concurrency statistics, MCP auth mode, and full policy status.
- `GET /ready` returns readiness-oriented bot/addon/concurrency state plus policy-store readiness.
- `GET /mcp/health` returns MCP-specific policy status and legacy-bearer configuration state.

A missing or unreachable Redis policy store degrades readiness and guild access remains fail-closed.

## Legacy/internal HTTP API

Bot-control and cookie-management routes remain available for deployment compatibility, but they are separate from MCP and do not inherit MCP OAuth or the Redis guild allowlist. Keep them behind a trusted network or an authenticated reverse proxy.

See [docs/http-api.md](docs/http-api.md) for the exact route list and request shapes.

## Architecture

```text
                         ChatGPT / MCP client
                                  |
                         OAuth + Streamable HTTP
                                  v
┌─────────────┐     ┌─────────────────────────┐     ┌─────────────┐
│   Discord   │<--->│      Discord Adapter    │<--->│  Lily-Core  │
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

Legacy HTTP routes are outside those four MCP layers and need deployment-level network/auth protection of their own.

## Testing

Source CI builds the Docker image, runs Python syntax compilation, executes the pytest suite, starts a Redis sidecar, launches the adapter container with `REDIS_URL`, and requires `/health` to report `mcp_policy_store_ready=true`.

Tests cover policy bootstrap and fail-closed behavior, Redis authority, runtime mutation/reload, atomic snapshot preservation, policy-write gating, audit persistence, the complete 60-tool MCP surface, rich message arguments, destructive annotations, extended Discord operations, media inspection, OAuth, addon lifecycle, and message-controller behavior.

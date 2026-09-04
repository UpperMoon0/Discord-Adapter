# Configuration reference

This document describes the runtime environment variables read by Discord Adapter. `.env.template` is the copyable example; this file explains semantics, defaults, and failure behavior.

## Discord bot and addons

| Variable | Default | Purpose |
| --- | --- | --- |
| `DISCORD_BOT_TOKEN` | unset | Enables the Discord gateway bot. Without it, the process stays alive in HTTP/MCP-only mode. |
| `DISCORD_MEMBERS_INTENT` | `false` | Enables Discord Server Members Intent in the client. Also enable the privileged intent in the Discord Developer Portal. Required for exhaustive `discord_list_members` paging and useful for reliable name-based member search. |
| `DISCORD_ADDONS` | empty | Comma-separated `discord_adapter.addons` entry-point IDs to load. Empty disables addons. `*` intentionally enables every installed addon. |
| `DISCORD_ADDON_STRICT` | `false` | If true, a missing or failed configured addon prevents bot startup. Otherwise failures are isolated and reported in health state. |

The adapter always requests Message Content Intent in code because Lily-Core sessions inspect ordinary message text. Enable **Message Content Intent** for the bot in the Discord Developer Portal when that chat behavior is used.

Boolean environment settings accept conventional truthy values such as `1`, `true`, `yes`, and `on`.

## Runtime guild access policy

| Variable | Default | Purpose |
| --- | --- | --- |
| `REDIS_URL` | unset | Redis connection used by the authoritative MCP guild policy. If missing or unavailable, policy readiness degrades and guild access fails closed. The template uses `redis://redis:6379/0` for the normal container network. |
| `DISCORD_ADMIN_GUILD_IDS` | empty | One-time bootstrap only when Redis has no policy. Comma-separated guild IDs; `*` intentionally seeds all-guild access. Redis is authoritative afterward. |
| `MCP_POLICY_WRITES_ENABLED` | `false` | Deployment-level gate for `discord_policy_allow_guild` and `discord_policy_remove_guild`. |
| `DISCORD_POLICY_REDIS_KEY` | `lily:discord-adapter:access-policy:v1` | Redis key holding the authoritative policy document. |
| `DISCORD_POLICY_AUDIT_REDIS_KEY` | `lily:discord-adapter:access-policy:audit:v1` | Redis list key holding bounded mutation audit records. |
| `DISCORD_POLICY_AUDIT_MAX_ENTRIES` | `100` | Requested maximum retained audit entries. The service bounds unsafe values internally. |

Changing `DISCORD_ADMIN_GUILD_IDS` after a policy has been seeded does not change the live policy. Use the privileged policy MCP tools or intentionally replace/reseed the Redis policy through deployment operations.

## MCP authentication and transport security

| Variable | Default | Purpose |
| --- | --- | --- |
| `MCP_PUBLIC_URL` | unset | Canonical public origin for OAuth, for example `https://lily-discord-adapter.example.com`. Outside loopback development it must use HTTPS. Must be configured together with `MCP_OAUTH_OWNER_TOKEN`. |
| `MCP_OAUTH_OWNER_TOKEN` | unset | Owner-approval secret for OAuth authorization. Minimum 32 characters. It is not an MCP bearer token. Must be configured together with `MCP_PUBLIC_URL`. |
| `MCP_OAUTH_STATE` | `/app/data/oauth-state.json` | Persistent file for dynamic client registrations and hashed token/grant state. |
| `MCP_OAUTH_ACCESS_TTL` | `1h` | Access-token lifetime. Supports integer values with optional `s`, `m`, `h`, or `d`; minimum 60 seconds. |
| `MCP_OAUTH_REFRESH_TTL` | `720h` | Refresh-token lifetime. Must be at least the access-token TTL. |
| `MCP_OAUTH_SERVER_NAME` | `Discord Adapter` | Display name exposed by the OAuth authorization server. |
| `MCP_BEARER_TOKEN` | unset | Legacy static bearer fallback used only when OAuth is not configured. If OAuth and bearer are both absent, `/mcp/` fails closed with HTTP 503. |
| `MCP_ALLOWED_HOSTS` | derived | Comma-separated MCP Host allowlist. Empty allows localhost and, when available, `lily-discord-adapter.<DOMAIN_NAME>` plus port variants. |
| `MCP_ALLOWED_ORIGINS` | empty | Comma-separated browser Origin allowlist for MCP transport security. Usually unnecessary for server-to-server clients. |
| `DOMAIN_NAME` | unset | Deployment domain used for service-discovery metadata and automatic MCP public-host derivation. |

OAuth supports authorization-code flow with PKCE S256, dynamic client registration, `mcp` and `offline_access` scopes, and refresh-token rotation.

The Streamable HTTP endpoint is configured for stateless, finite JSON responses so each MCP request completes with its HTTP response instead of retaining an application session or SSE stream.

## Discord message media inspection

| Variable | Default | Purpose |
| --- | --- | --- |
| `DISCORD_MEDIA_MAX_DOWNLOAD_BYTES` | `33554432` (32 MiB) | Maximum server-side media download accepted for MCP inspection. Non-positive/invalid values fall back to the default. |
| `DISCORD_MEDIA_MAX_DIRECT_IMAGE_BYTES` | `1048576` (1 MiB) | Maximum static image size returned directly as MCP image content. Larger static images are normalized to a bounded JPEG frame before being returned, reducing oversized base64 tool results. |
| `DISCORD_MEDIA_FFMPEG_TIMEOUT_SECONDS` | `20` | Timeout used for `ffmpeg`/`ffprobe` media processing. |
| `DISCORD_MEDIA_ALLOWED_HOSTS` | empty additions | Extra comma-separated HTTPS hosts that may be fetched for embedded media. These extend, rather than replace, the built-in Discord/Tenor/Giphy host allowlist. |

Attachments from already-authorized Discord messages are inspected through Discord attachment URLs. Embedded remote media is fetched only from trusted HTTPS hosts. Redirect following is disabled for the embed fetch path.

The Docker image installs `ffmpeg`, which also provides `ffprobe`. Static-image normalization does not run `ffprobe`; duration probing is reserved for animated images and video sampling.

## Concurrency and rate limits

| Variable | Default | Purpose |
| --- | --- | --- |
| `RATE_LIMIT_RPS` | `10` | Per-user/request rate configuration used by the message-processing limiter. |
| `MAX_CONCURRENT_REQUESTS` | `5` | Concurrent-request limit in the shared rate-limit configuration. |
| `BURST_LIMIT` | `20` | Burst allowance in the shared rate-limit configuration. |
| `MAX_CONCURRENT_MESSAGES` | `10` | Maximum Discord/Lily-Core messages processed concurrently by the queue manager. |
| `MESSAGE_QUEUE_SIZE` | `1000` | Maximum queued message count before new messages are rejected with a queue-full response. |
| `NUM_WORKERS` | `4` | Number of message-processing workers started by the concurrency manager. |

These values are parsed as integers during service initialization. Invalid non-integer values will fail startup rather than being silently corrected.

## Service and discovery

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `8004` | FastAPI/MCP HTTP listening port and Consul registration port. |
| `CONSUL_HTTP_ADDR` | `consul:8500` | Consul address used for Lily-Core discovery and service registration. |
| `DOMAIN_NAME` | unset | Also used by service discovery to advertise public deployment metadata. |

Lily-Core is optional for MCP-only administration. If Lily-Core cannot be discovered, the adapter remains available but reports `lily_core_available=false` and chat features cannot produce Lily-Core responses.

## Example production-oriented environment

```env
DISCORD_BOT_TOKEN=replace-me
DISCORD_MEMBERS_INTENT=true
DISCORD_ADDONS=quiz
DISCORD_ADDON_STRICT=true

REDIS_URL=redis://redis:6379/0
DISCORD_ADMIN_GUILD_IDS=123456789012345678
MCP_POLICY_WRITES_ENABLED=false
DISCORD_POLICY_REDIS_KEY=lily:discord-adapter:access-policy:v1
DISCORD_POLICY_AUDIT_REDIS_KEY=lily:discord-adapter:access-policy:audit:v1
DISCORD_POLICY_AUDIT_MAX_ENTRIES=100

MCP_PUBLIC_URL=https://lily-discord-adapter.example.com
MCP_OAUTH_OWNER_TOKEN=replace-with-at-least-32-random-characters
MCP_OAUTH_STATE=/app/data/oauth-state.json
MCP_OAUTH_ACCESS_TTL=1h
MCP_OAUTH_REFRESH_TTL=720h
MCP_OAUTH_SERVER_NAME=Discord Adapter
MCP_BEARER_TOKEN=
MCP_ALLOWED_HOSTS=
MCP_ALLOWED_ORIGINS=

DISCORD_MEDIA_MAX_DOWNLOAD_BYTES=33554432
DISCORD_MEDIA_MAX_DIRECT_IMAGE_BYTES=1048576
DISCORD_MEDIA_FFMPEG_TIMEOUT_SECONDS=20
DISCORD_MEDIA_ALLOWED_HOSTS=

RATE_LIMIT_RPS=10
MAX_CONCURRENT_REQUESTS=5
BURST_LIMIT=20
MAX_CONCURRENT_MESSAGES=10
MESSAGE_QUEUE_SIZE=1000
NUM_WORKERS=4

PORT=8004
CONSUL_HTTP_ADDR=consul:8500
DOMAIN_NAME=example.com
```

Do not commit real bot tokens, OAuth owner secrets, bearer tokens, or cookie files.

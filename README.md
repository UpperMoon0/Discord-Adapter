# Discord Adapter

Discord bot adapter for Lily-Core. The service connects Discord to Lily-Core and also exposes a guild-scoped Model Context Protocol (MCP) endpoint for ChatGPT administration.

## Features

- Discord bot integration with Lily-Core
- Text message processing
- Voice channel support (join/leave)
- Audio message handling
- Consul service discovery registration
- Health and readiness endpoints
- Streamable HTTP MCP endpoint at `/mcp/`
- Self-hosted OAuth 2.0 authorization-code + PKCE flow for ChatGPT
- Dynamic OAuth client registration with rotating refresh tokens
- Explicit per-guild MCP allowlist (fail closed by default)
- Semantic MCP tools for messages, moderation, members, roles, channels, permissions, webhooks, emoji/stickers, invites, threads, voice, server settings, and audit logs
- Legacy static bearer mode only as a compatibility fallback
- MCP Host/Origin allowlists for DNS-rebinding protection
- Cross-event-loop dispatch so FastAPI/MCP requests execute Discord operations on the bot's owning event loop

## Setup

### Prerequisites

- Python 3.11+
- Discord bot token
- Access to Lily-Core
- Optional: Discord **Server Members Intent** for reliable name-based member search

### Environment Variables

Create a `.env` file with the following variables:

```env
# Discord Configuration
DISCORD_BOT_TOKEN=your_discord_bot_token_here

# MCP may access only these Discord guild/server IDs.
# Comma-separated. The default (empty) exposes no guilds.
# Use * only if you intentionally want every guild Lily is in.
DISCORD_ADMIN_GUILD_IDS=123456789012345678,234567890123456789

# Enable only after enabling Server Members Intent in the Discord Developer Portal.
DISCORD_MEMBERS_INTENT=false

# Preferred MCP OAuth configuration.
MCP_PUBLIC_URL=https://lily-discord-adapter.nstut.cloud
MCP_OAUTH_OWNER_TOKEN=at-least-32-characters
MCP_OAUTH_STATE=/app/data/oauth-state.json
MCP_OAUTH_ACCESS_TTL=1h
MCP_OAUTH_REFRESH_TTL=720h
MCP_OAUTH_SERVER_NAME=Discord Adapter

# Legacy compatibility only. OAuth takes precedence when configured.
MCP_BEARER_TOKEN=

# Optional DNS-rebinding allowlists. If MCP_ALLOWED_HOSTS is empty, localhost
# is allowed and lily-discord-adapter.<DOMAIN_NAME> is added automatically.
MCP_ALLOWED_HOSTS=
MCP_ALLOWED_ORIGINS=

# Service Configuration
PORT=8004

# Consul Configuration
CONSUL_HTTP_ADDR=consul:8500
```

`DISCORD_ADMIN_GUILD_IDS` is an adapter-level boundary in addition to Discord's own permissions and role hierarchy. If the variable is missing or empty, MCP tools cannot read or mutate any guild.

The MCP SDK validates the HTTP `Host` header to prevent DNS rebinding. Lily's production deployment already supplies `DOMAIN_NAME`, so the adapter automatically allows `lily-discord-adapter.<DOMAIN_NAME>` plus localhost. For another hostname, set `MCP_ALLOWED_HOSTS` explicitly as a comma-separated list. `MCP_ALLOWED_ORIGINS` is normally unnecessary for server-to-server MCP clients and should only contain browser origins you intentionally support.

If OAuth is not configured, the adapter accepts `MCP_BEARER_TOKEN` as a legacy fallback. If neither OAuth nor the legacy bearer token is configured, `/mcp/` fails closed with HTTP 503 rather than becoming unauthenticated.

### Installation

```bash
pip install -r requirements.txt
python main.py
```

### Docker

```bash
docker build -t nstut/lily-discord-adapter .

docker run -d \
  --name lily-discord-adapter \
  -p 8004:8004 \
  -e DISCORD_BOT_TOKEN=your_token \
  -e DISCORD_ADMIN_GUILD_IDS=123456789012345678 \
  -e DOMAIN_NAME=nstut.cloud \
  -e MCP_PUBLIC_URL=https://lily-discord-adapter.nstut.cloud \
  -e MCP_OAUTH_OWNER_TOKEN=your_owner_approval_token \
  -e CONSUL_HTTP_ADDR=consul:8500 \
  nstut/lily-discord-adapter
```

## ChatGPT / MCP

The Streamable HTTP MCP endpoint is:

```text
https://<adapter-host>/mcp/
```

Use the trailing slash. Public deployments should use the built-in OAuth flow. The adapter exposes OAuth protected-resource metadata, authorization-server metadata, dynamic client registration, owner approval, authorization-code exchange with PKCE S256, and refresh-token rotation.

The OAuth endpoints are:

```text
/.well-known/oauth-protected-resource
/.well-known/oauth-protected-resource/mcp
/.well-known/oauth-authorization-server
/oauth/register
/oauth/authorize
/oauth/token
```

For production, `MCP_OAUTH_OWNER_TOKEN` is an **owner approval secret**, not an access token shared with ChatGPT. ChatGPT dynamically registers a client, redirects the owner to the adapter's approval page, and receives its own short-lived access token plus rotating refresh token after PKCE verification. Access/refresh values and client secrets are persisted only as SHA-256 hashes in `MCP_OAUTH_STATE`, which should live on the persistent `/app/data` volume with mode `0600`.

Changing `MCP_OAUTH_OWNER_TOKEN` invalidates persisted access and refresh grants on the next process start while preserving registered clients, matching Lily-Shell's owner-token rotation behavior.

The production Lily stack uses the same Key Vault owner approval secret for Lily-Shell and Discord Adapter (`lily-mcp-owner-token`), while each service keeps separate OAuth clients, authorization codes, access tokens, refresh tokens, state files, issuers, and resource audiences. A Lily-Shell access token is therefore not valid for Discord Adapter and vice versa.

The MCP server intentionally exposes semantic Discord operations instead of a raw Discord REST proxy or arbitrary command execution. This lets an MCP host resolve a server/member/channel/role first and then call one narrow operation with explicit IDs.

### Discovery and read tools

- `discord_list_servers` — allowed servers plus the bot permission/capability matrix used by the admin tools
- `discord_list_channels`
- `discord_find_members`
- `discord_get_member`
- `discord_read_messages`
- `discord_list_roles`
- `discord_get_audit_log`
- `discord_get_guild_settings`
- `discord_list_channel_permissions`
- `discord_list_webhooks`
- `discord_list_emojis`
- `discord_list_stickers`
- `discord_list_invites`
- `discord_list_threads`

### Messaging and moderation

- `discord_send_message`
- `discord_delete_message`
- `discord_pin_message`
- `discord_unpin_message`
- `discord_purge_messages`
- `discord_timeout_member`
- `discord_clear_timeout`
- `discord_kick_member`
- `discord_ban_member`
- `discord_unban_member`

`discord_purge_messages` scans at most 100 recent messages per call and may optionally filter by author and/or a content substring. There is deliberately no unbounded purge operation.

### Member and voice administration

- `discord_set_member_nickname`
- `discord_move_member_voice` — move to a voice/stage channel or disconnect with a null channel ID
- `discord_set_member_voice_state` — server mute/deafen

### Role administration

- `discord_add_role`
- `discord_remove_role`
- `discord_create_role`
- `discord_update_role`
- `discord_delete_role`

Role permission inputs use Discord permission flag names. Managed integration roles and the `@everyone` role are protected from unsupported edit/delete operations.

### Channel and permission administration

- `discord_create_text_channel`
- `discord_update_text_channel`
- `discord_delete_channel`
- `discord_move_channel`
- `discord_set_channel_permissions`
- `discord_clear_channel_permissions`

Channel overwrite values are explicit three-state values: `true` to allow, `false` to deny, and `null` to inherit. `discord_move_channel` can reorder a guild channel, move it under a category, clear its category, and optionally sync category permissions.

### Server settings

- `discord_update_guild_settings`

The tool covers the basic server settings that Discord exposes through the bot API: name, description, verification level, default notification level, explicit-content filter, AFK channel/timeout, and system channel.

### Webhooks

- `discord_create_webhook`
- `discord_update_webhook`
- `discord_delete_webhook`

Webhook discovery deliberately returns webhook metadata only. Webhook URLs/tokens are not exposed through MCP responses.

### Emoji and stickers

- `discord_create_emoji`
- `discord_update_emoji`
- `discord_delete_emoji`
- `discord_create_sticker`
- `discord_update_sticker`
- `discord_delete_sticker`

Create operations accept bounded base64 media payloads. The adapter rejects oversized decoded payloads before calling Discord.

### Invites and threads

- `discord_create_invite`
- `discord_delete_invite`
- `discord_create_thread`
- `discord_update_thread`
- `discord_delete_thread`

Invite creation is bounded to Discord's supported age/use ranges. Thread creation, archive/lock state, auto-archive duration, and slowmode are exposed as typed parameters.

### Scope and permission model

Every operation requires an explicit `guild_id` except the initial `discord_list_servers` discovery call. There is deliberately no bulk destructive endpoint; operating on multiple servers requires one explicit tool call per guild.

Messages sent through MCP disable Discord mentions by default, so text such as `@everyone`, `@here`, user mentions, and role mentions will not cause pings.

MCP does not bypass Discord. The bot must still have the corresponding Discord permission and must satisfy Discord role hierarchy rules for each operation. `discord_list_servers` reports the relevant capability flags so an MCP host can determine what the bot can do before attempting a write. Prefer granting only the permissions the bot actually needs rather than `Administrator`.

For reliable member discovery by name, enable **Server Members Intent** for the bot in the Discord Developer Portal and then set:

```env
DISCORD_MEMBERS_INTENT=true
```

Exact user-ID operations can still work without enabling the privileged intent.

## Existing HTTP API

The existing bot-control routes remain available under `/api/bot`, including status, enable/disable, guild/channel listing, and message sending. The MCP administration surface is separate and enforces its own guild allowlist.

## Bot Commands

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
│   Servers   │     │  FastAPI + MCP + bot    │     │  (C++)      │
└─────────────┘     └─────────────────────────┘     └─────────────┘
                              |
                              v
                         ┌─────────────┐
                         │   Consul    │
                         └─────────────┘
```

MCP administration is constrained by three layers:

1. OAuth client authorization using the owner approval secret.
2. `DISCORD_ADMIN_GUILD_IDS` in the adapter.
3. Discord bot permissions and role hierarchy inside each guild.

## Testing

CI builds the Docker image, runs Python syntax compilation, executes pytest, and starts the resulting container for a live `/health` check. MCP coverage includes a runtime SDK contract test that lists the server's tools and verifies the complete semantic surface and destructive annotations. OAuth coverage exercises metadata discovery, dynamic registration, owner approval, PKCE code exchange, code replay rejection, MCP bearer enforcement, refresh-token rotation, persistent hashed state, owner-token rotation, resource isolation, and fail-closed behavior.

## Docker Compose

The service can continue to be configured from the main Lily compose stack. Start the stack with:

```bash
docker compose up -d
```

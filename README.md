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
- Explicit per-guild MCP allowlist (fail closed by default)
- Semantic MCP tools for messages, moderation, members, roles, channels, permissions, webhooks, emoji/stickers, invites, threads, voice, server settings, and audit logs
- Optional bearer protection for generic MCP clients
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

# Optional inbound protection for generic MCP clients.
# Leave empty only when /mcp/ is protected by ChatGPT Secure MCP Tunnel,
# a private network, or an authenticating reverse proxy.
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
  -e CONSUL_HTTP_ADDR=consul:8500 \
  nstut/lily-discord-adapter
```

## ChatGPT / MCP

The Streamable HTTP MCP endpoint is:

```text
https://<adapter-host>/mcp/
```

Use the trailing slash. For a private deployment, prefer ChatGPT's Secure MCP Tunnel or another private/authenticated ingress. If the endpoint is exposed publicly, put OAuth or equivalent authentication at the edge. `MCP_BEARER_TOKEN` is available for generic MCP clients that can send an `Authorization: Bearer ...` header.

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
                          Streamable HTTP
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

1. Inbound tunnel/authentication or private network boundary.
2. `DISCORD_ADMIN_GUILD_IDS` in the adapter.
3. Discord bot permissions and role hierarchy inside each guild.

## Testing

CI builds the Docker image, runs Python syntax compilation, executes pytest, and starts the resulting container for a live `/health` check. MCP coverage includes a runtime SDK contract test that lists the server's tools and verifies the complete semantic surface and destructive annotations.

## Docker Compose

The service can continue to be configured from the main Lily compose stack. Start the stack with:

```bash
docker compose up -d
```

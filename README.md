# Lily-Discord-Adapter

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
- Discord message, moderation, role, channel, and audit-log tools
- Optional bearer protection for generic MCP clients
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

# Service Configuration
PORT=8004

# Consul Configuration
CONSUL_HTTP_ADDR=consul:8500
```

`DISCORD_ADMIN_GUILD_IDS` is an adapter-level boundary in addition to Discord's own permissions and role hierarchy. If the variable is missing or empty, MCP tools cannot read or mutate any guild.

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
  -e CONSUL_HTTP_ADDR=consul:8500 \
  nstut/lily-discord-adapter
```

## ChatGPT / MCP

The Streamable HTTP MCP endpoint is:

```text
https://<adapter-host>/mcp/
```

Use the trailing slash. For a private deployment, prefer ChatGPT's Secure MCP Tunnel or another private/authenticated ingress. If the endpoint is exposed publicly, put OAuth or equivalent authentication at the edge. `MCP_BEARER_TOKEN` is available for generic MCP clients that can send an `Authorization: Bearer ...` header.

The MCP server intentionally exposes semantic Discord operations instead of a raw Discord REST proxy or arbitrary command execution.

### Read tools

- `discord_list_servers`
- `discord_list_channels`
- `discord_find_members`
- `discord_get_member`
- `discord_read_messages`
- `discord_list_roles`
- `discord_get_audit_log`

### Write / moderation tools

- `discord_send_message`
- `discord_delete_message`
- `discord_timeout_member`
- `discord_clear_timeout`
- `discord_kick_member`
- `discord_ban_member`
- `discord_unban_member`
- `discord_add_role`
- `discord_remove_role`
- `discord_create_text_channel`
- `discord_update_text_channel`
- `discord_delete_channel`

Every mutation requires an explicit `guild_id`. There is deliberately no bulk destructive endpoint; operating on multiple servers requires one explicit tool call per guild.

Messages sent through MCP disable Discord mentions by default, so text such as `@everyone`, `@here`, user mentions, and role mentions will not cause pings.

### Discord permissions

MCP does not bypass Discord. Lily must still have the corresponding Discord permission and must satisfy Discord role hierarchy rules for each operation. Prefer granting only the permissions Lily actually needs rather than `Administrator`.

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
│   Discord   │<--->│ Lily-Discord-Adapter    │<--->│  Lily-Core  │
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

## Docker Compose

The service can continue to be configured from the main Lily compose stack. Start the stack with:

```bash
docker compose up -d
```

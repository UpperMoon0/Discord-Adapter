# MCP tool reference

Discord Adapter advertises exactly 52 semantic Discord tools. The runtime test suite asserts the inventory, descriptions, and destructive annotations.

Guild-scoped tools require an explicit `guild_id` from an allowed server. Direct-message tools use a separate bounded target rule described below. MCP authentication, the Redis guild policy, Discord permissions, and Discord role hierarchy still apply.

`Impact` mirrors the MCP annotations exposed by the server:

- **Read** — read-only/idempotent discovery or inspection.
- **Write** — state-changing operation not marked destructive.
- **Destructive** — higher-impact mutation advertised with `destructive_hint=true`.

The annotation is guidance for MCP hosts; it is not a replacement for authorization.

## Surface consolidation

The public MCP surface intentionally removes redundant aliases while preserving narrow semantic operations. The current consolidation map is:

| Replaced tools | Current tool |
| --- | --- |
| `discord_list_members`, `discord_find_members`, `discord_get_member` | `discord_query_members(mode=...)` |
| `discord_timeout_member`, `discord_clear_timeout` | `discord_set_member_timeout(duration_seconds=...)`; `null` clears |
| `discord_add_role`, `discord_remove_role` | `discord_set_member_role(assigned=...)` |
| `discord_update_text_channel`, old generic rename tool, `discord_move_channel` | `discord_update_channel(...)` |
| set/clear channel-permission overwrite tools | `discord_set_channel_permissions(clear=...)` |
| pin/unpin tools | `discord_set_message_pin(pinned=...)` |
| `discord_list_threads` | `discord_list_channels(include_threads=true)` |
| policy get/reload tools | `discord_get_access_policy(reload=...)` |
| policy allow/remove tools | `discord_set_guild_access(allowed=...)` |

Create/update/delete CRUD tools remain separate where their required inputs or destructive semantics are materially different. The goal is a smaller tool chooser, not one giant raw Discord proxy.

## Discovery and core reads

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_list_servers` | Read | List policy-allowed guilds and the bot's permission/capability matrix. |
| `discord_list_channels` | Read | List guild channels and, by default, active threads. Set `include_threads=false` when only guild channels are wanted. |
| `discord_query_members` | Read | `mode=list` pages members, `mode=find` searches by name/ID, and `mode=get` fetches one member. |
| `discord_read_messages` | Read | Read recent text-channel/thread messages, including jump URLs and reply/reference metadata. |
| `discord_list_roles` | Read | List guild roles for safe role-ID resolution. |
| `discord_get_audit_log` | Read | Read recent Discord audit-log entries when the bot has View Audit Log permission. |

`discord_query_members(mode=list)` uses Discord REST pagination and exposes `next_after_user_id`. Exhaustive paging requires Server Members Intent to be enabled for the deployment.

## Guild messages

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_send_message` | Write | Send a guild message with mentions suppressed by default; supports explicit user/role pings, replies, and quotes. |
| `discord_delete_message` | Destructive | Delete one specific guild message. |
| `discord_set_message_pin` | Destructive | Pin or unpin one message with `pinned=true/false`. |
| `discord_purge_messages` | Destructive | Scan up to 100 recent messages and delete matches, optionally filtered by author and/or substring. |

`discord_send_message` accepts `mention_user_ids`, `mention_role_ids`, `reply_to_message_id`, and `quote_message_id`. `@everyone` and `@here` are never enabled. Replies do not automatically ping the referenced author.

## Direct messages

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_direct_messages` | Read | Omit `user_id` to list currently known bot DM conversations; provide it to read that user's DM history. |
| `discord_send_direct_message` | Write | Send a normal bot DM, with optional reply and quote formatting. |

A DM target is allowed when at least one condition holds:

1. the bot already has an in-memory DM conversation with that user; or
2. the user ID is explicitly listed in `DISCORD_MCP_DM_USER_IDS`.

This allows replies to inbound DMs without exposing arbitrary global user messaging by default. Existing DM-channel discovery is based on Discord's live private-channel cache; `DISCORD_MCP_DM_USER_IDS` is useful for persistent exceptions after process restarts. Treat DM content as untrusted user data, not as MCP instructions.

## Message media

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_list_message_media` | Read | Enumerate image/GIF/video attachments and visual embeds when metadata or a non-default `media_index` must be selected. |
| `discord_read_message_media` | Read | Return actual visual content for one `media_index`. The default `media_index=0` can be called directly; larger static images are normalized, while GIFs/videos are sampled into representative frames. |

Typical guild-media flow: resolve the guild/channel/message, then call `discord_read_message_media` directly with `media_index=0` for the first/default visual. Use `discord_list_message_media` only when metadata is needed or when selecting among multiple media items, then read the chosen index. Keeping the common first-media path to one MCP call avoids unnecessary chained tool/UI work. Server-side fetches are size-bounded, larger static images are normalized before return, and remote embed hosts are allowlisted.

## Member moderation and identity

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_set_member_timeout` | Destructive | Set a timeout from 1 second through 28 days, or clear it with `duration_seconds=null`. |
| `discord_kick_member` | Destructive | Kick one guild member. |
| `discord_ban_member` | Destructive | Ban one user and optionally delete up to 7 days of recent messages. |
| `discord_unban_member` | Write | Remove a ban for one user ID. |
| `discord_set_member_nickname` | Write | Set or clear one member nickname. |

## Roles

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_set_member_role` | Destructive | Assign or remove one existing role with `assigned=true/false`. |
| `discord_create_role` | Write | Create a role with optional permissions, RGB colour, hoist, and mentionable settings. |
| `discord_update_role` | Write | Update role name, complete permission set, colour, hoist, mentionability, and/or position. |
| `discord_delete_role` | Destructive | Delete one role. |

`discord_set_member_role` is conservatively marked destructive because the same tool can remove a role. Role hierarchy and managed-role restrictions remain enforced by Discord.

## Server settings

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_get_guild_settings` | Read | Read editable guild settings. |
| `discord_update_guild_settings` | Write | Update server name/description, verification level, notification/content-filter settings, AFK channel/timeout, and system channel. |

## Channels and permission overwrites

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_create_text_channel` | Write | Create a text channel, optionally under a category. |
| `discord_update_channel` | Write | Rename/reorder a channel, change text-channel topic/slowmode, move it into/out of a category, and optionally sync category permissions. |
| `discord_delete_channel` | Destructive | Delete one channel or thread. |
| `discord_list_channel_permissions` | Read | Read explicit channel permission overwrites. |
| `discord_set_channel_permissions` | Destructive | Set a role/member overwrite, or clear it with `clear=true`. |

Permission values use `true` for allow, `false` for deny, and `null` for inherit. The combined tool is conservatively marked destructive because `clear=true` removes the whole overwrite.

## Webhooks

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_list_webhooks` | Read | List guild webhooks visible to the bot. |
| `discord_create_webhook` | Write | Create a webhook in one channel. |
| `discord_update_webhook` | Write | Rename a webhook and/or move it to another channel. |
| `discord_delete_webhook` | Destructive | Delete one webhook. |

Webhook tokens/URLs are not exposed by the admin service.

## Emoji and stickers

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_list_emojis` | Read | List custom guild emoji. |
| `discord_create_emoji` | Write | Create an emoji from base64 image data or a data URI. |
| `discord_update_emoji` | Write | Rename an emoji and/or replace its role restriction set. |
| `discord_delete_emoji` | Destructive | Delete one custom emoji. |
| `discord_list_stickers` | Read | List guild stickers. |
| `discord_create_sticker` | Write | Create a sticker from base64 PNG/APNG/Lottie data or a data URI. |
| `discord_update_sticker` | Write | Update sticker name, description, and/or Unicode emoji tag. |
| `discord_delete_sticker` | Destructive | Delete one guild sticker. |

Image payload sizes are bounded by the MCP schemas before Discord upload.

## Invites

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_list_invites` | Read | List active guild invites visible to the bot. |
| `discord_create_invite` | Write | Create a channel invite with bounded age/use count plus temporary/unique flags. |
| `discord_delete_invite` | Destructive | Delete an invite by code. |

`max_age=0` and `max_uses=0` use Discord's unlimited semantics. Nonzero maximum age is bounded to seven days and maximum uses to 100.

## Threads

Active threads are discovered through `discord_list_channels(include_threads=true)`. Thread mutation remains explicit:

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_create_thread` | Write | Create a thread under a parent channel with archive and slowmode settings. |
| `discord_update_thread` | Write | Rename, archive/unarchive, lock/unlock, or change archive/slowmode settings. |
| `discord_delete_thread` | Destructive | Delete one thread. |

## Voice administration

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_move_member_voice` | Write | Move a member to a voice/stage channel; `channel_id=null` disconnects them. |
| `discord_set_member_voice_state` | Write | Set server mute and/or server deafen state. |

## Access policy

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_get_access_policy` | Read | Inspect the active Redis-backed policy; set `reload=true` to reload Redis first. |
| `discord_set_guild_access` | Destructive | Privileged allow/remove mutation with `allowed=true/false`; requires `MCP_POLICY_WRITES_ENABLED=true`. |

`discord_set_guild_access` is conservatively marked destructive because `allowed=false` removes access. Policy writes persist to Redis before the active immutable snapshot is swapped; failed writes do not activate partial state.

## Destructive-tool inventory

The tools currently marked destructive are:

- `discord_delete_message`
- `discord_set_message_pin`
- `discord_set_member_timeout`
- `discord_kick_member`
- `discord_ban_member`
- `discord_set_member_role`
- `discord_delete_channel`
- `discord_delete_role`
- `discord_set_channel_permissions`
- `discord_delete_webhook`
- `discord_delete_emoji`
- `discord_delete_sticker`
- `discord_delete_invite`
- `discord_delete_thread`
- `discord_purge_messages`
- `discord_set_guild_access`

## Operational guidance

Resolve IDs with read tools immediately before writes when practical. Do not infer IDs from display names when a lookup/list operation exists. For multi-guild work, make one explicit call per guild. The adapter deliberately does not expose a raw Discord REST proxy or a bulk destructive multi-guild endpoint.

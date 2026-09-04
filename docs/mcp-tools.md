# MCP tool reference

Discord Adapter advertises exactly 61 semantic Discord tools. The runtime test suite asserts that this inventory is complete and that every tool has a model-readable description.

All guild-scoped tools require an explicit `guild_id` from an allowed server. MCP authentication, the Redis guild policy, Discord permissions, and Discord role hierarchy all still apply.

`Impact` below mirrors the MCP annotations exposed by the server:

- **Read** — read-only/idempotent discovery or inspection.
- **Write** — state-changing operation not marked destructive.
- **Destructive** — higher-impact mutation advertised with `destructive_hint=true`.

The annotation is guidance for MCP hosts; it is not a replacement for authorization.

## Discovery and core reads

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_list_servers` | Read | List policy-allowed guilds and the bot's permission/capability matrix. |
| `discord_list_channels` | Read | List channels in one allowed guild. |
| `discord_list_members` | Read | Exhaustively page through current guild members using Discord REST; exposes explicit server nickname and optional bot filtering. |
| `discord_find_members` | Read | Find members by username, display/global name, or exact user ID. |
| `discord_get_member` | Read | Read one member's roles and timeout state. |
| `discord_read_messages` | Read | Read recent text-channel/thread messages, including jump URLs and reply/reference metadata. |
| `discord_list_roles` | Read | List guild roles for safe role-ID resolution. |
| `discord_get_audit_log` | Read | Read recent Discord audit-log entries when the bot has View Audit Log permission. |

## Messages

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_send_message` | Write | Send a message with mentions suppressed by default; supports explicit user/role pings, replies, and quotes. |
| `discord_delete_message` | Destructive | Delete one specific message. |
| `discord_pin_message` | Write | Pin one message in a channel or thread. |
| `discord_unpin_message` | Destructive | Remove one message pin. |
| `discord_purge_messages` | Destructive | Scan up to 100 recent messages and delete matches, optionally filtered by author and/or substring. |

### Rich message semantics

`discord_send_message` accepts:

- `mention_user_ids`: users to prepend and explicitly allow as mentions;
- `mention_role_ids`: roles to prepend and explicitly allow as mentions;
- `reply_to_message_id`: message in the same channel to reply to;
- `quote_message_id`: message in the same channel whose author/content is rendered above the new content.

`@everyone` and `@here` are never enabled. A reply does not automatically ping the original author unless that user is also explicitly listed in `mention_user_ids`.

## Message media

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_list_message_media` | Read | Enumerate image/GIF/video attachments and visual embeds when metadata or a non-default `media_index` must be selected. |
| `discord_read_message_media` | Read | Return actual visual content for one `media_index`. The default `media_index=0` can be called directly; larger static images are normalized, while GIFs/videos are sampled into representative frames. |

Typical flow:

1. Resolve the guild/channel/message with normal discovery/read tools.
2. For the first/default visual, call `discord_read_message_media` directly with `media_index=0`. Do not list first.
3. Use `discord_list_message_media` only when metadata is needed or when selecting among multiple media items, then call `discord_read_message_media` with the chosen index.
4. For GIF/video inspection, optionally set `max_frames` from 1 to 6.

Keeping the common first-media path to one MCP tool call also avoids unnecessary chained tool/UI work in clients. Server-side fetches are size-bounded, large static image results are normalized before return, and remote embed hosts are allowlisted. See [configuration](configuration.md#discord-message-media-inspection).

## Member moderation and identity

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_timeout_member` | Destructive | Timeout one member for 1 second through 28 days. |
| `discord_clear_timeout` | Write | Clear a member timeout. |
| `discord_kick_member` | Destructive | Kick one guild member. |
| `discord_ban_member` | Destructive | Ban one user and optionally delete up to 7 days of recent messages. |
| `discord_unban_member` | Write | Remove a ban for one user ID. |
| `discord_set_member_nickname` | Write | Set or clear one member nickname. |

## Roles

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_add_role` | Write | Assign one existing role to one member. |
| `discord_remove_role` | Destructive | Remove one existing role from one member. |
| `discord_create_role` | Write | Create a role with optional permissions, RGB colour, hoist, and mentionable settings. |
| `discord_update_role` | Write | Update role name, complete permission set, colour, hoist, mentionability, and/or position. |
| `discord_delete_role` | Destructive | Delete one role. |

Role operations remain constrained by the bot member's highest role and Discord's managed-role rules.

## Server settings

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_get_guild_settings` | Read | Read editable guild settings. |
| `discord_update_guild_settings` | Write | Update server name/description, verification level, notification/content-filter settings, AFK channel/timeout, and system channel. |

Supported AFK timeout values are 60, 300, 900, 1800, or 3600 seconds. The tool exposes explicit clear flags for AFK/system channels so omission is distinguishable from clearing.

## Channels and permission overwrites

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_create_text_channel` | Write | Create a text channel, optionally under a category. |
| `discord_update_text_channel` | Write | Update text-channel name, topic, and/or slowmode delay. |
| `discord_update_channel` | Write | Rename a generic guild channel/category. Use this when the target is not necessarily a text channel. |
| `discord_move_channel` | Write | Reorder a channel and/or move it between categories; can clear the category and control permission sync. |
| `discord_delete_channel` | Destructive | Delete one channel or thread. |
| `discord_list_channel_permissions` | Read | Read explicit channel permission overwrites. |
| `discord_set_channel_permissions` | Write | Set a role/member overwrite using permission values `true` (allow), `false` (deny), or `null` (inherit). |
| `discord_clear_channel_permissions` | Destructive | Delete one role/member overwrite from a channel. |

`discord_update_channel` and `discord_update_text_channel` are intentionally different: the generic tool provides safe rename coverage across guild channel types, while the text-specific tool exposes text-only settings such as topic and slowmode.

## Webhooks

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_list_webhooks` | Read | List guild webhooks visible to the bot. |
| `discord_create_webhook` | Write | Create a webhook in one channel. |
| `discord_update_webhook` | Write | Rename a webhook and/or move it to another channel. |
| `discord_delete_webhook` | Destructive | Delete one webhook. |

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

`max_age=0` and `max_uses=0` use Discord's unlimited semantics. Nonzero maximum age is bounded to seven days and maximum uses to 100 by the tool schema.

## Threads

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_list_threads` | Read | List active guild threads. |
| `discord_create_thread` | Write | Create a thread under a parent channel with archive and slowmode settings. |
| `discord_update_thread` | Write | Rename, archive/unarchive, lock/unlock, or change archive/slowmode settings. |
| `discord_delete_thread` | Destructive | Delete one thread. |

Supported auto-archive durations are 60, 1440, 4320, or 10080 minutes, subject to Discord/server capability.

## Voice administration

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_move_member_voice` | Write | Move a member to a voice/stage channel; `channel_id=null` disconnects them. |
| `discord_set_member_voice_state` | Write | Set server mute and/or server deafen state. |

## Access policy

| Tool | Impact | Purpose |
| --- | --- | --- |
| `discord_get_access_policy` | Read | Inspect the active Redis-backed policy, revision/source, store readiness, and policy-write capability. |
| `discord_reload_access_policy` | Read | Reload the authoritative Redis policy and atomically replace the in-memory snapshot only on success. |
| `discord_policy_allow_guild` | Write | Privileged allowlist expansion. Requires `MCP_POLICY_WRITES_ENABLED=true`. |
| `discord_policy_remove_guild` | Destructive | Privileged removal of one guild from the policy. Requires `MCP_POLICY_WRITES_ENABLED=true`. |

Policy writes persist to Redis before the active immutable snapshot is swapped. A failed Redis transaction does not activate a partially written policy.

## Destructive-tool inventory

For clients that want a compact approval list, the tools currently marked destructive are:

- `discord_delete_message`
- `discord_timeout_member`
- `discord_kick_member`
- `discord_ban_member`
- `discord_remove_role`
- `discord_delete_channel`
- `discord_delete_role`
- `discord_clear_channel_permissions`
- `discord_delete_webhook`
- `discord_delete_emoji`
- `discord_delete_sticker`
- `discord_delete_invite`
- `discord_delete_thread`
- `discord_unpin_message`
- `discord_purge_messages`
- `discord_policy_remove_guild`

## Operational guidance

Resolve IDs with read tools immediately before writes when practical. Do not infer IDs from display names when a lookup/list tool exists. For multi-guild work, make one explicit call per guild. The adapter deliberately does not expose a raw Discord REST proxy or a bulk destructive multi-guild endpoint.

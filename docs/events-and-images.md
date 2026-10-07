# Discord image uploads and real-time event relay

Both capabilities are opt-in and covered by offline tests. These features
do **not** introduce a public unauthenticated HTTP control route and do
**not** send live Discord messages during CI.

## Upload an image with MCP

The authenticated MCP tool `discord_send_image` posts one real image attachment
to a channel in a guild allowed by the Redis access policy. It accepts:

- `guild_id`, `channel_id` (Discord snowflakes, preserved as strings);
- `image_base64` (base64-encoded raw image bytes; no `data:` URL prefix);
- optional `filename` (PNG/JPEG/WebP/GIF), `caption`, `reply_to_message_id`.

The upload is limited to **8 MiB decoded** by default (smaller limit available
through `DISCORD_IMAGE_MAX_UPLOAD_BYTES`). Only matching image signatures and
safe filenames are accepted. No arbitrary local file paths, remote downloads,
or untrusted URL fetching are exposed by the write tool.

Mentions are **always disabled**. A caption containing `@everyone` or a user
mention cannot ping anyone. A reply also does not ping its author. The tool
posts immediately; tests mock all Discord API calls.

The caller is responsible for producing the base64 image bytes from a source
it is allowed to read. There is currently no automatic translation from a
ChatGPT conversation's local sandbox path to a Discord attachment; passing
`/mnt/data/image.png` or a file ID as `image_base64` will be rejected.

## Relay new Discord messages to an automation worker

The Discord bot already receives gateway `on_message` events. The optional
`DiscordEventRelay` sends a **signed, scoped HTTPS webhook** immediately
when one of the explicitly configured users posts in one of the explicitly
configured channels in an approved guild.

This is an outbound notification to an administrator-owned automation
endpoint, **not** a ChatGPT Work event-triggered scheduled task. ChatGPT Work
currently supports native events from Gmail, Slack, and GitHub; a custom MCP
tool cannot register a Discord event trigger in Work by itself.

Example configuration:

```env
DISCORD_EVENT_WEBHOOK_URL=https://your-automation-host.example/discord-events
DISCORD_EVENT_WEBHOOK_SECRET=use-a-random-secret-at-least-32-bytes-long
DISCORD_EVENT_GUILD_IDS=736926591246008350
DISCORD_EVENT_CHANNEL_IDS=1053701182801072219
DISCORD_EVENT_USER_IDS=679291758332346368
```

All five entries are examples, **not deployment defaults**. No webhook is
sent unless the URL and a strong secret are explicitly configured. Guild and
channel allowlists are required. `DISCORD_EVENT_USER_IDS` is optional: leave
empty only if monitoring every user in the allowlisted channels is intended.
The caller's guild must also pass the current Redis MCP access policy, which
is rechecked at dispatch time.

The webhook JSON contains only:

```json
{
  "event_type": "discord.message.created",
  "version": 1,
  "event_id": "1557468104555102229",
  "guild_id": "736926591246008350",
  "channel_id": "1053701182801072219",
  "user_id": "679291758332346368",
  "content": "message text, limited to 2000 characters",
  "attachments": [{"filename": "image.png", "url": "https://cdn.discordapp.com/..."}]
}
```

The headers include `Content-Type: application/json`,
`X-Discord-Event-ID`, `X-Discord-Event-Timestamp`, and `X-Discord-Event-Signature: sha256=HEX_DIGEST`.
The hex digest is `HMAC-SHA256(secret, ASCII_timestamp + b\".\" + exact_UTF8_request_bytes)`, with `ASCII_timestamp` from the `X-Discord-Event-Timestamp` header (Unix seconds). Verify the HMAC in constant time, reject timestamps older than 5 minutes or too far in the future, and de-duplicate event IDs **before** acting on the event.
Treat the body and attachment URLs as untrusted user input. Use the
`event_id` for consumer-side deduplication.

The relay is asynchronous and does not block the Discord message callback.
It has a 256-event bounded in-memory queue, a 2048-message recent-ID window,
5-second HTTP timeout, no HTTP redirects or proxy environment variables, and
up to 3 attempts for 429/5xx or network errors. It never posts to Discord.
Events may be dropped on overload or restart: this is **not** a durable
message queue. A production consumer should reconcile from
`discord_read_messages` after disconnects if completeness is required.

The automation receiver—not this relay—must decide whether to respond,
send a reply through authenticated MCP when authorized, and stop its watch
when its objective is complete. To disable the relay, remove
`DISCORD_EVENT_WEBHOOK_URL` and restart the adapter.

## Development and release safety

The source CI workflow builds without a Discord token, and mock-based tests
do not access the Discord API or an external webhook. Do not set real
`DISCORD_BOT_TOKEN` or `DISCORD_EVENT_WEBHOOK_URL` in test environments.
No bot deployment is required to review this PR.

Image sending will be available to connected MCP clients **after** the
reviewed server version is deployed and the plugin tool list is refreshed.

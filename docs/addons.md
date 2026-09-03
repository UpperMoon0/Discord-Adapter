# Discord Adapter addons

Discord Adapter supports independently packaged addons through Python entry points.
Addon packages are installed into the same runtime image as Discord Adapter, but
remain separate repositories and should not import private adapter services.

## Entry point

Register one entry point in the `discord_adapter.addons` group:

```toml
[project.entry-points."discord_adapter.addons"]
quiz = "quiz_discord_addon:QuizAddon"
```

The entry-point name is the deployment-facing addon ID. Addons are opt-in:

```env
DISCORD_ADDONS=quiz
```

Use `DISCORD_ADDONS=*` only when intentionally enabling every installed addon.
Set `DISCORD_ADDON_STRICT=true` when a missing or failed configured addon should
prevent the Discord bot from connecting.

## Public API

External packages should depend only on `discord_adapter_sdk`:

```python
from discord_adapter_sdk import DiscordAddonContext


class QuizAddon:
    name = "quiz"

    async def setup(self, context: DiscordAddonContext) -> None:
        context.bot.tree.add_command(...)

    async def shutdown(self) -> None:
        ...
```

`DiscordAddonContext` deliberately exposes only the Discord bot. Addons may
register slash commands, views, listeners, and other Discord features through
that bot. Do not import policy, MCP, Lily-Core, or other private adapter
services from an addon.

## Lifecycle

For each Discord bot instance the host performs:

1. register built-in Discord Adapter handlers;
2. discover explicitly enabled `discord_adapter.addons` entry points;
3. instantiate each addon and await `setup(context)` during `setup_hook`;
4. connect to Discord;
5. synchronize the combined application-command tree;
6. call optional addon `shutdown()` hooks when that bot instance stops.

By default one failed addon is isolated and reported in `/health` and `/ready`.
Strict mode changes addon load failures into bot startup failures.

## Packaging and deployment

The deployment image must install addon packages before starting Discord Adapter.
NsTut-CICD should own that composition rather than vendoring addon source into
this repository. For example, a final image may contain Discord Adapter plus a
pinned `quiz` package and set `DISCORD_ADDONS=quiz`.

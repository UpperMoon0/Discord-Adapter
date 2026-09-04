# Discord Adapter addons

Discord Adapter supports independently packaged addons through Python entry points. Addon packages are installed into the same runtime image/environment as Discord Adapter but remain separate repositories and should depend only on the public `discord_adapter_sdk` contract.

The host deliberately exposes a narrow context so addon code does not become coupled to private policy, MCP, Lily-Core, or deployment internals.

## Entry point

Register one entry point in the `discord_adapter.addons` group:

```toml
[project.entry-points."discord_adapter.addons"]
quiz = "quiz_discord_addon:QuizAddon"
```

The entry-point name (`quiz` above) is the deployment-facing addon ID. Discovery is deterministic: discovered entry points are sorted by name before loading.

Enable addons explicitly:

```env
DISCORD_ADDONS=quiz
```

Multiple IDs are comma-separated:

```env
DISCORD_ADDONS=quiz,status
```

Use `DISCORD_ADDONS=*` only when intentionally enabling every installed addon. Empty/unset `DISCORD_ADDONS` disables all addons even if packages are installed.

Set:

```env
DISCORD_ADDON_STRICT=true
```

when a missing or failed configured addon should prevent the Discord bot from starting. The default is `false`.

## Public API

External packages should import only from `discord_adapter_sdk`:

```python
from discord_adapter_sdk import DiscordAddonContext


class QuizAddon:
    name = "quiz"

    async def setup(self, context: DiscordAddonContext) -> None:
        context.bot.tree.add_command(...)

    async def shutdown(self) -> None:
        ...
```

`DiscordAddonContext` currently exposes only:

```python
context.bot
```

The object is the live `discord.ext.commands.Bot` instance. Through it, addons may register application commands, listeners, views, cogs, and other normal Discord.py features.

Do **not** import these private adapter internals from an addon:

- Redis access-policy services;
- MCP server/tool registration modules;
- Lily-Core services;
- bot-control/cookie controllers;
- deployment-specific state or globals.

If an addon needs a new stable host capability, extend `discord_adapter_sdk` deliberately instead of reaching into a private service.

## Addon object contract

The entry point may resolve to either:

- an addon instance; or
- a class, which the host instantiates with no constructor arguments.

The resolved object must expose an async-compatible `setup(context)` method. If `setup` is missing, non-callable, or returns a non-awaitable value, loading fails for that addon.

`shutdown()` is optional. If present it may be synchronous or async. Shutdown failures are logged and do not prevent the host from continuing shutdown of other addons.

The `name` attribute is part of the public `DiscordAddon` protocol for addon identity/documentation, while deployment selection is performed by the Python entry-point name in `DISCORD_ADDONS`.

## Lifecycle

For each Discord bot instance the host performs:

1. register built-in Discord Adapter handlers;
2. discover explicitly enabled `discord_adapter.addons` entry points;
3. report configured IDs that are not installed;
4. resolve/instantiate each selected addon and await `setup(context)` during `setup_hook`;
5. connect to Discord;
6. synchronize the combined application-command tree from `on_ready`;
7. call optional addon `shutdown()` hooks in reverse successful-load order when that bot instance stops.

Addon loading is attempted exactly once per `AddonManager` / bot instance. Changing `DISCORD_ADDONS` in the environment does not hot-load or unload an addon in an already-created bot instance; restart/recreate the bot process/instance through deployment when changing addon composition.

## Failure behavior

With the default `DISCORD_ADDON_STRICT=false`:

- missing configured addon IDs are recorded as failures;
- an exception from one addon's import/instantiation/setup is isolated;
- other selected addons continue loading;
- the bot can continue startup;
- failure details appear in addon health status.

With `DISCORD_ADDON_STRICT=true`, a missing configured addon or load/setup failure aborts bot startup.

## Health and readiness visibility

`/health` and `/ready` include a `discord_addons` object with:

```json
{
  "entrypoint_group": "discord_adapter.addons",
  "enabled": ["quiz"],
  "strict": false,
  "load_attempted": true,
  "loaded": ["quiz"],
  "failed": {}
}
```

When `DISCORD_ADDONS=*`, the `enabled` field is reported as `["*"]`.

A missing configured addon is reported with a failure similar to:

```text
NotInstalled: no matching addon entry point
```

Use these fields when diagnosing deployment composition before inspecting addon-specific logs.

## Packaging and deployment

The deployment image/environment must install addon packages before starting Discord Adapter. NsTut-CICD should own that composition rather than vendoring niche addon source into this repository.

Conceptually, a composed runtime contains:

```text
Discord Adapter
+ pinned addon package A
+ pinned addon package B
+ DISCORD_ADDONS=a,b
```

Keep addon versions pinned by deployment so a restart cannot silently resolve a different addon build.

Addon package names do not have to match their entry-point IDs, but keeping them related makes deployment diagnosis easier.

## Command registration guidance

Because built-in and addon application commands share the same bot command tree, avoid duplicate slash-command names. Register commands during `setup(context)` so they are present before the host synchronizes the combined tree.

If an addon installs listeners or other resources that need explicit cleanup, implement `shutdown()` and unregister/close those resources there.

## Minimal example

```python
from discord import app_commands
from discord_adapter_sdk import DiscordAddonContext


class StatusAddon:
    name = "status"

    async def setup(self, context: DiscordAddonContext) -> None:
        @app_commands.command(name="status", description="Show addon status")
        async def status(interaction):
            await interaction.response.send_message("ok", ephemeral=True)

        context.bot.tree.add_command(status)

    async def shutdown(self) -> None:
        pass
```

Package it with:

```toml
[project.entry-points."discord_adapter.addons"]
status = "status_addon:StatusAddon"
```

and enable it with:

```env
DISCORD_ADDONS=status
```

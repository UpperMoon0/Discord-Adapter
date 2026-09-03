"""Discovery and lifecycle management for independently packaged Discord addons."""

from __future__ import annotations

import inspect
import logging
import os
from importlib.metadata import entry_points
from typing import Iterable

from discord.ext import commands

from discord_adapter_sdk import DISCORD_ADDON_ENTRYPOINT_GROUP, DiscordAddonContext

logger = logging.getLogger("lily-discord-adapter.addons")


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_enabled_addons(raw: str | None) -> frozenset[str] | None:
    if raw is None or not raw.strip() or raw.strip() == "*":
        return None

    return frozenset(part.strip() for part in raw.split(",") if part.strip())


class AddonManager:
    """Load Python entry-point addons into one Discord bot instance."""

    def __init__(
        self,
        *,
        enabled_addons: frozenset[str] | None = None,
        strict: bool = False,
        entry_point_provider=None,
    ) -> None:
        self.enabled_addons = enabled_addons
        self.strict = strict
        self._entry_point_provider = entry_point_provider
        self._loaded: dict[str, object] = {}
        self._failed: dict[str, str] = {}
        self._load_attempted = False

    @classmethod
    def from_env(cls) -> "AddonManager":
        return cls(
            enabled_addons=_parse_enabled_addons(os.getenv("DISCORD_ADDONS")),
            strict=_env_flag("DISCORD_ADDON_STRICT", False),
        )

    def _discover_all(self) -> list[object]:
        if self._entry_point_provider is not None:
            discovered = list(self._entry_point_provider())
        else:
            discovered_all = entry_points()
            if hasattr(discovered_all, "select"):
                discovered = list(discovered_all.select(group=DISCORD_ADDON_ENTRYPOINT_GROUP))
            else:  # pragma: no cover - compatibility with older importlib metadata
                discovered = list(discovered_all.get(DISCORD_ADDON_ENTRYPOINT_GROUP, ()))

        discovered.sort(key=lambda item: item.name)
        return discovered

    def _discover(self) -> Iterable[object]:
        discovered = self._discover_all()
        if self.enabled_addons is None:
            return discovered
        return [item for item in discovered if item.name in self.enabled_addons]

    async def load(self, bot: commands.Bot) -> None:
        """Discover and initialize addons exactly once for this bot instance."""
        if self._load_attempted:
            return
        self._load_attempted = True

        discovered = list(self._discover())
        if self.enabled_addons is not None:
            discovered_names = {item.name for item in discovered}
            missing = sorted(self.enabled_addons - discovered_names)
            for name in missing:
                self._failed[name] = "NotInstalled: no matching addon entry point"
                logger.error(
                    "Configured Discord addon %s is not installed in entry-point group %s",
                    name,
                    DISCORD_ADDON_ENTRYPOINT_GROUP,
                )
            if missing and self.strict:
                raise RuntimeError(
                    "configured Discord addons are not installed: " + ", ".join(missing)
                )

        context = DiscordAddonContext(bot=bot)
        for entry_point in discovered:
            name = entry_point.name
            try:
                target = entry_point.load()
                addon = target() if inspect.isclass(target) else target
                setup = getattr(addon, "setup", None)
                if not callable(setup):
                    raise TypeError("addon must expose setup(context)")

                result = setup(context)
                if not inspect.isawaitable(result):
                    raise TypeError("addon setup(context) must be async")
                await result

                self._loaded[name] = addon
                logger.info("Loaded Discord addon %s", name)
            except Exception as exc:
                self._failed[name] = f"{type(exc).__name__}: {exc}"
                logger.exception("Failed to load Discord addon %s", name)
                if self.strict:
                    raise

    async def shutdown(self) -> None:
        """Shut down loaded addons in reverse registration order."""
        for name, addon in reversed(tuple(self._loaded.items())):
            shutdown = getattr(addon, "shutdown", None)
            if not callable(shutdown):
                continue
            try:
                result = shutdown()
                if inspect.isawaitable(result):
                    await result
                logger.info("Stopped Discord addon %s", name)
            except Exception:
                logger.exception("Failed to stop Discord addon %s", name)

        self._loaded.clear()

    def status(self) -> dict:
        return {
            "entrypoint_group": DISCORD_ADDON_ENTRYPOINT_GROUP,
            "enabled": sorted(self.enabled_addons) if self.enabled_addons is not None else ["*"],
            "strict": self.strict,
            "load_attempted": self._load_attempted,
            "loaded": sorted(self._loaded),
            "failed": dict(sorted(self._failed.items())),
        }

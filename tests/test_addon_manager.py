from __future__ import annotations

import pytest

from discord_adapter_sdk import DiscordAddonContext
from services.addon_manager import AddonManager, _parse_enabled_addons


class FakeEntryPoint:
    def __init__(self, name: str, target):
        self.name = name
        self._target = target

    def load(self):
        return self._target


class GoodAddon:
    name = "good"
    setup_calls = 0
    shutdown_calls = 0
    seen_bot = None

    async def setup(self, context: DiscordAddonContext) -> None:
        type(self).setup_calls += 1
        type(self).seen_bot = context.bot

    async def shutdown(self) -> None:
        type(self).shutdown_calls += 1


class BrokenAddon:
    name = "broken"

    async def setup(self, context: DiscordAddonContext) -> None:
        raise RuntimeError("boom")


@pytest.fixture(autouse=True)
def reset_addon_state():
    GoodAddon.setup_calls = 0
    GoodAddon.shutdown_calls = 0
    GoodAddon.seen_bot = None


def test_parse_enabled_addons():
    assert _parse_enabled_addons(None) is None
    assert _parse_enabled_addons("") is None
    assert _parse_enabled_addons("*") is None
    assert _parse_enabled_addons(" quiz, status ,quiz ") == frozenset({"quiz", "status"})


@pytest.mark.asyncio
async def test_loads_selected_addon_once_and_shuts_it_down():
    bot = object()
    manager = AddonManager(
        enabled_addons=frozenset({"good"}),
        entry_point_provider=lambda: [
            FakeEntryPoint("ignored", BrokenAddon),
            FakeEntryPoint("good", GoodAddon),
        ],
    )

    await manager.load(bot)
    await manager.load(bot)

    assert GoodAddon.setup_calls == 1
    assert GoodAddon.seen_bot is bot
    assert manager.status()["loaded"] == ["good"]
    assert manager.status()["failed"] == {}

    await manager.shutdown()
    assert GoodAddon.shutdown_calls == 1


@pytest.mark.asyncio
async def test_broken_addon_is_isolated_by_default():
    manager = AddonManager(
        entry_point_provider=lambda: [
            FakeEntryPoint("broken", BrokenAddon),
            FakeEntryPoint("good", GoodAddon),
        ],
    )

    await manager.load(object())

    assert manager.status()["loaded"] == ["good"]
    assert manager.status()["failed"]["broken"] == "RuntimeError: boom"


@pytest.mark.asyncio
async def test_missing_selected_addon_is_reported():
    manager = AddonManager(
        enabled_addons=frozenset({"quiz"}),
        entry_point_provider=lambda: [],
    )

    await manager.load(object())

    assert manager.status()["loaded"] == []
    assert manager.status()["failed"]["quiz"] == (
        "NotInstalled: no matching addon entry point"
    )


@pytest.mark.asyncio
async def test_strict_mode_fails_fast():
    manager = AddonManager(
        strict=True,
        entry_point_provider=lambda: [FakeEntryPoint("broken", BrokenAddon)],
    )

    with pytest.raises(RuntimeError, match="boom"):
        await manager.load(object())


@pytest.mark.asyncio
async def test_strict_mode_rejects_missing_selected_addon():
    manager = AddonManager(
        enabled_addons=frozenset({"quiz"}),
        strict=True,
        entry_point_provider=lambda: [],
    )

    with pytest.raises(RuntimeError, match="quiz"):
        await manager.load(object())

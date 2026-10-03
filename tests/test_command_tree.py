from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
from discord import app_commands
from discord.ext import commands

from controllers.command_controller import CommandController
from services.access_policy_service import PolicySnapshot, access_policy_service
from services.command_tree import WhitelistedCommandTree


def policy(monkeypatch, guilds=(), all_guilds=False):
    monkeypatch.setattr(access_policy_service, "_snapshot", PolicySnapshot(
        version=1, revision=1, all_guilds=all_guilds,
        guilds=MappingProxyType({guild_id: frozenset() for guild_id in guilds}),
        source="test",
    ))


def bot_and_tree():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none(),
                       application_id=42, tree_cls=WhitelistedCommandTree)
    tree = bot.tree
    tree._http = SimpleNamespace(
        bulk_upsert_global_commands=AsyncMock(return_value=[]),
        bulk_upsert_guild_commands=AsyncMock(return_value=[]),
    )
    return bot, tree


def add_slash(tree, name, guild=None):
    async def callback(interaction):
        pass
    cmd = app_commands.Command(name=name, description="Test", callback=callback)
    tree.add_command(cmd, guild=guild)
    return cmd


def interaction(guild_id, kind=discord.InteractionType.application_command):
    return SimpleNamespace(
        guild_id=guild_id, type=kind, command_failed=False,
        response=SimpleNamespace(is_done=lambda: False, send_message=AsyncMock(),
                                 autocomplete=AsyncMock()),
        data={"name": "join", "type": 1},
    )


@pytest.mark.asyncio
async def test_startup_removes_global_and_denied_guild_commands(monkeypatch):
    policy(monkeypatch, [123])
    bot, tree = bot_and_tree()
    bot._connection._guilds = {i: discord.Object(id=i) for i in [123, 999]}
    add_slash(tree, "join")
    add_slash(tree, "addon")
    await tree.reconcile()
    tree._http.bulk_upsert_global_commands.assert_awaited_once_with(42, payload=[])
    calls = tree._http.bulk_upsert_guild_commands.await_args_list
    assert calls[0].args == (42, 999)
    assert calls[0].kwargs["payload"] == []
    assert {p["name"] for p in calls[1].kwargs["payload"]} == {"join", "addon"}
    assert {c.name for c in tree.get_commands()} == {"join", "addon"}
    await tree.reconcile()
    assert tree._http.bulk_upsert_guild_commands.await_count == 2


@pytest.mark.asyncio
async def test_addon_explicit_sync_cannot_bypass_approval(monkeypatch):
    policy(monkeypatch)
    _, tree = bot_and_tree()
    add_slash(tree, "addon", discord.Object(id=999))
    await tree.sync()
    await tree.sync(guild=discord.Object(id=999))
    tree._http.bulk_upsert_global_commands.assert_awaited_once_with(42, payload=[])
    tree._http.bulk_upsert_guild_commands.assert_awaited_once_with(42, 999, payload=[])


@pytest.mark.asyncio
async def test_policy_grant_revoke_and_regrant_reconcile(monkeypatch):
    policy(monkeypatch, [123])
    bot, tree = bot_and_tree()
    bot._connection._guilds = {123: discord.Object(id=123)}
    add_slash(tree, "join")
    await tree.reconcile()
    policy(monkeypatch)
    assert await tree.interaction_check(interaction(123)) is False
    await tree.reconcile()
    assert tree._http.bulk_upsert_guild_commands.await_args.kwargs["payload"] == []
    policy(monkeypatch, [123])
    await tree.reconcile()
    assert tree._http.bulk_upsert_guild_commands.await_args.kwargs["payload"][0]["name"] == "join"


@pytest.mark.asyncio
async def test_failed_guild_sync_is_retried_and_other_guilds_continue(monkeypatch):
    policy(monkeypatch, [123, 456])
    bot, tree = bot_and_tree()
    bot._connection._guilds = {i: discord.Object(id=i) for i in [123, 456]}
    add_slash(tree, "join")
    tree._http.bulk_upsert_guild_commands.side_effect = [RuntimeError("Discord unavailable"), [], []]
    await tree.reconcile()
    await tree.reconcile()
    assert [call.args[1] for call in tree._http.bulk_upsert_guild_commands.await_args_list] == [123, 456, 123]


@pytest.mark.asyncio
async def test_guild_addon_override_and_context_menus_are_preserved(monkeypatch):
    policy(monkeypatch, [123])
    _, tree = bot_and_tree()
    guild = discord.Object(id=123)
    add_slash(tree, "status")
    specific = add_slash(tree, "status", guild)
    specific.description = "Guild addon"
    async def inspect_message(interaction: discord.Interaction, message: discord.Message):
        pass
    tree.add_command(app_commands.ContextMenu(name="Inspect", callback=inspect_message))
    await tree.sync(guild=guild)
    payload = tree._http.bulk_upsert_guild_commands.await_args.kwargs["payload"]
    assert len(payload) == 2
    assert next(p for p in payload if p["name"] == "status")["description"] == "Guild addon"
    assert next(p for p in payload if p["name"] == "Inspect")["type"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("guild_id", [None, 999])
@pytest.mark.parametrize("kind", [discord.InteractionType.application_command,
                                  discord.InteractionType.autocomplete])
async def test_denied_dispatch_stops_before_any_command_callback(monkeypatch, guild_id, kind):
    policy(monkeypatch, [123])
    _, tree = bot_and_tree()
    request = interaction(guild_id, kind)
    await tree._call(request)
    assert request.command_failed is True
    if kind == discord.InteractionType.autocomplete:
        request.response.autocomplete.assert_awaited_once_with([])
        request.response.send_message.assert_not_awaited()
    else:
        request.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["join", "play", "skip"])
async def test_all_builtin_commands_use_shared_policy_gate(monkeypatch, name):
    policy(monkeypatch)
    bot, tree = bot_and_tree()
    music = SimpleNamespace(join_channel=AsyncMock(), add_to_queue=AsyncMock(), skip=AsyncMock())
    CommandController(bot, None, None, music)
    request = interaction(999)
    request.data["name"] = name
    await tree._call(request)
    music.join_channel.assert_not_awaited()
    music.add_to_queue.assert_not_awaited()
    music.skip.assert_not_awaited()


@pytest.mark.asyncio
async def test_approved_and_wildcard_policy_allow_execution_but_never_dms(monkeypatch):
    _, tree = bot_and_tree()
    policy(monkeypatch, [123])
    assert await tree.interaction_check(interaction(123)) is True
    assert await tree.prefix_check(SimpleNamespace(guild=discord.Object(id=123))) is True
    assert await tree.prefix_check(SimpleNamespace(guild=discord.Object(id=999))) is False
    policy(monkeypatch, all_guilds=True)
    assert await tree.interaction_check(interaction(999)) is True
    assert await tree.interaction_check(interaction(None)) is False
    assert await tree.prefix_check(SimpleNamespace(guild=None)) is False


@pytest.mark.asyncio
async def test_host_installs_policy_for_addon_prefix_commands():
    from main import create_discord_bot
    bot = create_discord_bot()
    assert isinstance(bot.tree, WhitelistedCommandTree)
    assert bot.tree.prefix_check in bot._checks
    await bot.close()



@pytest.mark.asyncio
async def test_global_cleanup_failure_keeps_retry_task_and_close_cancels_it():
    from main import create_discord_bot
    bot = create_discord_bot()
    bot.tree.reconcile = AsyncMock(side_effect=RuntimeError('Discord unavailable'))
    with pytest.raises(RuntimeError):
        await bot.reconcile_commands()
    task = bot._command_policy_task
    assert task is not None
    with pytest.raises(RuntimeError):
        await bot.reconcile_commands()
    assert bot._command_policy_task is task
    await bot.close()
    assert task.done()


@pytest.mark.asyncio
async def test_new_guild_and_command_removal_are_reconciled(monkeypatch):
    policy(monkeypatch, [123, 456])
    bot, tree = bot_and_tree()
    bot._connection._guilds = {123: discord.Object(id=123)}
    add_slash(tree, 'addon')
    await tree.reconcile()
    bot._connection._guilds[456] = discord.Object(id=456)
    await tree.reconcile()
    assert tree._http.bulk_upsert_guild_commands.await_args.args == (42, 456)
    tree.remove_command('addon')
    await tree.reconcile()
    assert all(call.kwargs['payload'] == [] for call in tree._http.bulk_upsert_guild_commands.await_args_list[-2:])


@pytest.mark.asyncio
async def test_global_cleanup_failure_does_not_block_guilds_and_is_retried(monkeypatch):
    policy(monkeypatch, [123])
    bot, tree = bot_and_tree()
    bot._connection._guilds = {i: discord.Object(id=i) for i in [123, 999]}
    add_slash(tree, "join")
    tree._http.bulk_upsert_global_commands.side_effect = [
        RuntimeError("Global endpoint unavailable"),
        RuntimeError("Global endpoint unavailable"),
        [],
    ]

    await tree.reconcile()
    assert tree._globals_cleared is False
    calls = tree._http.bulk_upsert_guild_commands.await_args_list
    assert [call.args[1] for call in calls] == [999, 123]
    assert calls[0].kwargs["payload"] == []
    assert calls[1].kwargs["payload"][0]["name"] == "join"

    # Revocation must still remove guild commands while global cleanup fails.
    policy(monkeypatch)
    await tree.reconcile()
    assert tree._globals_cleared is False
    assert tree._http.bulk_upsert_guild_commands.await_args.args == (42, 123)
    assert tree._http.bulk_upsert_guild_commands.await_args.kwargs["payload"] == []

    await tree.reconcile()
    assert tree._globals_cleared is True
    assert tree._http.bulk_upsert_global_commands.await_count == 3
    assert tree._http.bulk_upsert_guild_commands.await_count == 3
    await tree.reconcile()
    assert tree._http.bulk_upsert_global_commands.await_count == 3
    await bot.close()

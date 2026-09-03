from types import MappingProxyType

import pytest

from services.access_policy_service import PolicySnapshot, access_policy_service


_LEGACY_DISCORD_BEHAVIOR_TESTS = {
    "test_discord_admin_extensions.py",
    "test_extended_guild_capabilities.py",
}


@pytest.fixture(autouse=True)
def _runtime_policy_for_legacy_discord_behavior_tests(monkeypatch, request):
    """Give older Discord-behavior tests a real runtime-policy snapshot.

    Those suites historically patched DISCORD_ADMIN_GUILD_IDS only to get past
    the guild boundary. The policy service itself is covered separately; here we
    keep the production guild-check path intact and install an immutable snapshot
    allowing their shared test guild (123).
    """
    if request.node.path.name not in _LEGACY_DISCORD_BEHAVIOR_TESTS:
        return

    snapshot = PolicySnapshot(
        version=1,
        revision=1,
        all_guilds=False,
        guilds=MappingProxyType({123: frozenset()}),
        source="test_fixture",
    )
    monkeypatch.setattr(access_policy_service, "_snapshot", snapshot)

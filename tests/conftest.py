import os

import pytest

from services.extended_discord_admin_service import ExtendedDiscordAdminService


_LEGACY_ENV_POLICY_TESTS = {
    "test_discord_admin_extensions.py",
    "test_extended_guild_capabilities.py",
}


def _legacy_env_allows(guild_id: int) -> bool:
    raw = os.getenv("DISCORD_ADMIN_GUILD_IDS", "").strip()
    if not raw:
        return False
    if raw == "*":
        return True
    allowed = set()
    for value in raw.split(","):
        value = value.strip()
        if not value:
            continue
        try:
            allowed.add(int(value))
        except ValueError:
            continue
    return guild_id in allowed


@pytest.fixture(autouse=True)
def _bridge_legacy_env_policy_tests(monkeypatch, request):
    """Keep pre-policy service tests focused on Discord behavior, not Redis setup.

    New access-policy tests exercise the real runtime snapshot. These two older
    suites historically used an env patch merely to get past the guild boundary,
    so emulate that boundary only inside those test modules.
    """
    if request.node.path.name not in _LEGACY_ENV_POLICY_TESTS:
        return

    monkeypatch.setattr(
        ExtendedDiscordAdminService,
        "is_guild_allowed",
        lambda self, guild_id: _legacy_env_allows(guild_id),
    )

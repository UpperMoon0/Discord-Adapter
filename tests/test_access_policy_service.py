import json
import os
from unittest.mock import patch

import pytest

from services.access_policy_service import AccessPolicyService


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.ops = []

    def set(self, key, value):
        self.ops.append(("set", key, value))
        return self

    def lpush(self, key, value):
        self.ops.append(("lpush", key, value))
        return self

    def ltrim(self, key, start, end):
        self.ops.append(("ltrim", key, start, end))
        return self

    async def execute(self):
        if self.redis.fail_execute:
            raise RuntimeError("simulated Redis transaction failure")
        for op in self.ops:
            if op[0] == "set":
                _, key, value = op
                self.redis.data[key] = value
            elif op[0] == "lpush":
                _, key, value = op
                self.redis.lists.setdefault(key, []).insert(0, value)
            elif op[0] == "ltrim":
                _, key, start, end = op
                self.redis.lists[key] = self.redis.lists.get(key, [])[start : end + 1]
        return [True] * len(self.ops)


class FakeRedis:
    def __init__(self):
        self.data = {}
        self.lists = {}
        self.fail_ping = False
        self.fail_get = False
        self.fail_execute = False
        self.closed = False

    async def ping(self):
        if self.fail_ping:
            raise RuntimeError("simulated Redis ping failure")
        return True

    async def get(self, key):
        if self.fail_get:
            raise RuntimeError("simulated Redis get failure")
        return self.data.get(key)

    def pipeline(self, transaction=True):
        assert transaction is True
        return FakePipeline(self)

    async def aclose(self):
        self.closed = True


def make_service(redis, *, audit_max_entries=100):
    return AccessPolicyService(
        redis_url="redis://policy.test:6379/0",
        audit_max_entries=audit_max_entries,
        redis_factory=lambda *args, **kwargs: redis,
    )


@pytest.mark.asyncio
async def test_empty_redis_fails_closed():
    redis = FakeRedis()
    service = make_service(redis)

    with patch.dict(os.environ, {}, clear=True):
        status = await service.initialize()

    assert status["store_ready"] is True
    assert status["configured"] is False
    assert status["source"] == "redis_empty"
    assert service.is_guild_allowed(123) is False


@pytest.mark.asyncio
async def test_env_bootstrap_seeds_redis_once_and_redis_is_authoritative_afterward():
    redis = FakeRedis()
    service = make_service(redis)

    with patch.dict(os.environ, {"DISCORD_ADMIN_GUILD_IDS": "123,456"}, clear=True):
        await service.initialize()

    persisted = json.loads(redis.data[service.policy_key])
    assert sorted(persisted["guilds"]) == ["123", "456"]
    assert service.is_guild_allowed(123) is True

    reloaded = make_service(redis)
    with patch.dict(os.environ, {"DISCORD_ADMIN_GUILD_IDS": "999"}, clear=True):
        await reloaded.initialize()

    assert reloaded.is_guild_allowed(123) is True
    assert reloaded.is_guild_allowed(999) is False
    assert reloaded.status()["source"] == "redis"


@pytest.mark.asyncio
async def test_allow_and_remove_guild_runtime_updates():
    redis = FakeRedis()
    service = make_service(redis)

    with patch.dict(
        os.environ,
        {"DISCORD_ADMIN_GUILD_IDS": "123", "MCP_POLICY_WRITES_ENABLED": "true"},
        clear=True,
    ):
        await service.initialize()
        allowed = await service.allow_guild(456, caller_context={"subject": "test"})
        assert allowed["success"] is True
        assert allowed["changed"] is True
        assert service.is_guild_allowed(456) is True

        removed = await service.remove_guild(123, caller_context={"subject": "test"})
        assert removed["success"] is True
        assert removed["changed"] is True
        assert service.is_guild_allowed(123) is False
        assert service.is_guild_allowed(456) is True


@pytest.mark.asyncio
async def test_reload_policy_swaps_snapshot_from_redis():
    redis = FakeRedis()
    service = make_service(redis)

    with patch.dict(os.environ, {"DISCORD_ADMIN_GUILD_IDS": "123"}, clear=True):
        await service.initialize()

    payload = json.loads(redis.data[service.policy_key])
    payload["revision"] += 1
    payload["guilds"] = {"999": {"allowed": True, "capabilities": []}}
    redis.data[service.policy_key] = json.dumps(payload)

    result = await service.reload()

    assert result["success"] is True
    assert service.is_guild_allowed(123) is False
    assert service.is_guild_allowed(999) is True
    assert service.status()["source"] == "redis"


@pytest.mark.asyncio
async def test_redis_mutation_failure_keeps_previous_snapshot_intact():
    redis = FakeRedis()
    service = make_service(redis)

    with patch.dict(
        os.environ,
        {"DISCORD_ADMIN_GUILD_IDS": "123", "MCP_POLICY_WRITES_ENABLED": "true"},
        clear=True,
    ):
        await service.initialize()
        previous = service.snapshot
        redis.fail_execute = True

        result = await service.allow_guild(456)

    assert result["success"] is False
    assert service.snapshot is previous
    assert service.is_guild_allowed(123) is True
    assert service.is_guild_allowed(456) is False


@pytest.mark.asyncio
async def test_policy_writes_are_disabled_by_default():
    redis = FakeRedis()
    service = make_service(redis)

    with patch.dict(os.environ, {"DISCORD_ADMIN_GUILD_IDS": "123"}, clear=True):
        await service.initialize()
        result = await service.allow_guild(456)

    assert result["success"] is False
    assert "disabled" in result["message"].lower()
    assert service.is_guild_allowed(456) is False
    assert service.status()["policy_writes_enabled"] is False


@pytest.mark.asyncio
async def test_policy_status_reports_store_source_and_revision():
    redis = FakeRedis()
    service = make_service(redis)

    with patch.dict(os.environ, {"DISCORD_ADMIN_GUILD_IDS": "321"}, clear=True):
        status = await service.initialize()

    assert status == {
        "configured": True,
        "all_guilds": False,
        "guild_ids": [321],
        "version": 1,
        "revision": 1,
        "source": "env_bootstrap",
        "redis_configured": True,
        "redis_available": True,
        "store_ready": True,
        "policy_writes_enabled": False,
        "last_error": None,
    }


@pytest.mark.asyncio
async def test_audit_log_is_persisted_and_bounded():
    redis = FakeRedis()
    service = make_service(redis, audit_max_entries=10)

    with patch.dict(
        os.environ,
        {"DISCORD_ADMIN_GUILD_IDS": "100", "MCP_POLICY_WRITES_ENABLED": "true"},
        clear=True,
    ):
        await service.initialize()
        for guild_id in range(200, 212):
            result = await service.allow_guild(guild_id, caller_context={"actor": "pytest"})
            assert result["success"] is True

    entries = redis.lists[service.audit_key]
    assert len(entries) == 10
    newest = json.loads(entries[0])
    assert newest["action"] == "allow_guild"
    assert newest["guild_id"] == 211
    assert newest["caller"] == {"actor": "pytest"}
    assert "timestamp" in newest
    assert "previous_state" in newest
    assert "new_state" in newest


@pytest.mark.asyncio
async def test_reload_failure_preserves_previous_snapshot():
    redis = FakeRedis()
    service = make_service(redis)

    with patch.dict(os.environ, {"DISCORD_ADMIN_GUILD_IDS": "123"}, clear=True):
        await service.initialize()

    previous = service.snapshot
    redis.fail_get = True
    result = await service.reload()

    assert result["success"] is False
    assert service.snapshot is previous
    assert service.is_guild_allowed(123) is True


@pytest.mark.asyncio
async def test_close_closes_async_redis_client():
    redis = FakeRedis()
    service = make_service(redis)

    with patch.dict(os.environ, {}, clear=True):
        await service.initialize()
    await service.close()

    assert redis.closed is True
    assert service.status()["store_ready"] is False

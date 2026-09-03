"""Redis-backed runtime access policy for Discord MCP administration."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Mapping

from redis.asyncio import Redis

logger = logging.getLogger("lily-discord-adapter")

POLICY_VERSION = 1
DEFAULT_POLICY_KEY = "lily:discord-adapter:access-policy:v1"
DEFAULT_AUDIT_KEY = "lily:discord-adapter:access-policy:audit:v1"


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class PolicySnapshot:
    """Immutable policy snapshot used by synchronous guild checks."""

    version: int
    revision: int
    all_guilds: bool
    guilds: Mapping[int, frozenset[str]]
    source: str

    @property
    def configured(self) -> bool:
        return self.all_guilds or bool(self.guilds)

    def allows(self, guild_id: int) -> bool:
        return self.all_guilds or guild_id in self.guilds


class AccessPolicyService:
    """Own Redis I/O and atomically swap immutable runtime policy snapshots."""

    def __init__(
        self,
        *,
        redis_url: str | None = None,
        policy_key: str | None = None,
        audit_key: str | None = None,
        audit_max_entries: int | None = None,
        redis_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.redis_url = redis_url if redis_url is not None else os.getenv("REDIS_URL", "").strip()
        self.policy_key = policy_key or os.getenv("DISCORD_POLICY_REDIS_KEY", DEFAULT_POLICY_KEY)
        self.audit_key = audit_key or os.getenv("DISCORD_POLICY_AUDIT_REDIS_KEY", DEFAULT_AUDIT_KEY)
        configured_max = audit_max_entries
        if configured_max is None:
            try:
                configured_max = int(os.getenv("DISCORD_POLICY_AUDIT_MAX_ENTRIES", "100"))
            except ValueError:
                configured_max = 100
        self.audit_max_entries = max(10, min(configured_max, 1000))
        self._redis_factory = redis_factory or Redis.from_url
        self._redis: Any | None = None
        self._mutation_lock = asyncio.Lock()
        self._redis_available = False
        self._store_ready = False
        self._last_error: str | None = None
        self._snapshot = self._empty_snapshot("uninitialized")

    @staticmethod
    def _empty_snapshot(source: str, revision: int = 0) -> PolicySnapshot:
        return PolicySnapshot(
            version=POLICY_VERSION,
            revision=revision,
            all_guilds=False,
            guilds=MappingProxyType({}),
            source=source,
        )

    @property
    def snapshot(self) -> PolicySnapshot:
        return self._snapshot

    @property
    def writes_enabled(self) -> bool:
        return _env_flag("MCP_POLICY_WRITES_ENABLED", False)

    def is_guild_allowed(self, guild_id: int) -> bool:
        return self._snapshot.allows(guild_id)

    def status(self) -> dict[str, Any]:
        snapshot = self._snapshot
        return {
            "configured": snapshot.configured,
            "all_guilds": snapshot.all_guilds,
            "guild_ids": sorted(snapshot.guilds),
            "version": snapshot.version,
            "revision": snapshot.revision,
            "source": snapshot.source,
            "redis_configured": bool(self.redis_url),
            "redis_available": self._redis_available,
            "store_ready": self._store_ready,
            "policy_writes_enabled": self.writes_enabled,
            "last_error": self._last_error,
        }

    def _new_client(self) -> Any:
        return self._redis_factory(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )

    @staticmethod
    def _normalize_payload(raw: str | bytes) -> dict[str, Any]:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("policy payload must be a JSON object")
        return payload

    @classmethod
    def _snapshot_from_payload(cls, raw: str | bytes, source: str) -> PolicySnapshot:
        payload = cls._normalize_payload(raw)
        version = payload.get("version")
        revision = payload.get("revision")
        all_guilds = payload.get("all_guilds", False)
        guilds_raw = payload.get("guilds", {})

        if version != POLICY_VERSION:
            raise ValueError(f"unsupported policy version: {version!r}")
        if not isinstance(revision, int) or revision < 1:
            raise ValueError("policy revision must be a positive integer")
        if not isinstance(all_guilds, bool):
            raise ValueError("all_guilds must be boolean")
        if not isinstance(guilds_raw, dict):
            raise ValueError("guilds must be an object")

        guilds: dict[int, frozenset[str]] = {}
        for raw_guild_id, entry in guilds_raw.items():
            try:
                guild_id = int(raw_guild_id)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid guild ID: {raw_guild_id!r}") from exc
            if guild_id <= 0 or not isinstance(entry, dict):
                raise ValueError(f"invalid guild policy entry: {raw_guild_id!r}")
            if entry.get("allowed") is not True:
                raise ValueError(f"guild {guild_id} must explicitly set allowed=true")
            capabilities = entry.get("capabilities", [])
            if not isinstance(capabilities, list) or not all(
                isinstance(item, str) and item.strip() for item in capabilities
            ):
                raise ValueError(f"invalid capabilities for guild {guild_id}")
            guilds[guild_id] = frozenset(capabilities)

        return PolicySnapshot(
            version=version,
            revision=revision,
            all_guilds=all_guilds,
            guilds=MappingProxyType(guilds),
            source=source,
        )

    @staticmethod
    def _payload_from_snapshot(snapshot: PolicySnapshot) -> dict[str, Any]:
        return {
            "version": POLICY_VERSION,
            "revision": snapshot.revision,
            "all_guilds": snapshot.all_guilds,
            "guilds": {
                str(guild_id): {
                    "allowed": True,
                    "capabilities": sorted(capabilities),
                }
                for guild_id, capabilities in snapshot.guilds.items()
            },
        }

    @staticmethod
    def _bootstrap_snapshot_from_env() -> PolicySnapshot | None:
        raw = os.getenv("DISCORD_ADMIN_GUILD_IDS", "").strip()
        if not raw:
            return None
        if raw == "*":
            return PolicySnapshot(
                version=POLICY_VERSION,
                revision=1,
                all_guilds=True,
                guilds=MappingProxyType({}),
                source="env_bootstrap",
            )

        guilds: dict[int, frozenset[str]] = {}
        for value in raw.split(","):
            value = value.strip()
            if not value:
                continue
            try:
                guild_id = int(value)
            except ValueError:
                logger.warning("Ignoring invalid DISCORD_ADMIN_GUILD_IDS bootstrap entry: %s", value)
                continue
            if guild_id > 0:
                guilds[guild_id] = frozenset()
        if not guilds:
            return None
        return PolicySnapshot(
            version=POLICY_VERSION,
            revision=1,
            all_guilds=False,
            guilds=MappingProxyType(guilds),
            source="env_bootstrap",
        )

    @staticmethod
    def _state_for_audit(snapshot: PolicySnapshot) -> dict[str, Any]:
        return {
            "revision": snapshot.revision,
            "all_guilds": snapshot.all_guilds,
            "guild_ids": sorted(snapshot.guilds),
        }

    def _audit_entry(
        self,
        *,
        action: str,
        guild_id: int | None,
        previous: PolicySnapshot,
        new: PolicySnapshot,
        caller_context: Mapping[str, Any] | None,
    ) -> str:
        return json.dumps(
            {
                "action": action,
                "guild_id": guild_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "previous_state": self._state_for_audit(previous),
                "new_state": self._state_for_audit(new),
                "caller": dict(caller_context or {}),
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    async def _persist_with_audit(
        self,
        *,
        action: str,
        guild_id: int | None,
        previous: PolicySnapshot,
        new: PolicySnapshot,
        caller_context: Mapping[str, Any] | None,
    ) -> None:
        if self._redis is None:
            raise RuntimeError("Redis policy store is not configured")
        payload = json.dumps(self._payload_from_snapshot(new), separators=(",", ":"), sort_keys=True)
        audit = self._audit_entry(
            action=action,
            guild_id=guild_id,
            previous=previous,
            new=new,
            caller_context=caller_context,
        )
        pipe = self._redis.pipeline(transaction=True)
        pipe.set(self.policy_key, payload)
        pipe.lpush(self.audit_key, audit)
        pipe.ltrim(self.audit_key, 0, self.audit_max_entries - 1)
        await pipe.execute()

    async def initialize(self) -> dict[str, Any]:
        """Connect to Redis and load or one-time bootstrap the authoritative policy."""
        if not self.redis_url:
            self._redis_available = False
            self._store_ready = False
            self._last_error = "REDIS_URL is not configured"
            self._snapshot = self._empty_snapshot("redis_unconfigured")
            logger.error("Discord MCP policy store is unavailable: REDIS_URL is not configured")
            return self.status()

        if self._redis is None:
            self._redis = self._new_client()

        try:
            await self._redis.ping()
            self._redis_available = True
            raw = await self._redis.get(self.policy_key)
            if raw is not None:
                self._snapshot = self._snapshot_from_payload(raw, "redis")
            else:
                bootstrap = self._bootstrap_snapshot_from_env()
                if bootstrap is None:
                    self._snapshot = self._empty_snapshot("redis_empty")
                else:
                    previous = self._empty_snapshot("redis_empty")
                    await self._persist_with_audit(
                        action="bootstrap_from_env",
                        guild_id=None,
                        previous=previous,
                        new=bootstrap,
                        caller_context={"surface": "startup", "source": "DISCORD_ADMIN_GUILD_IDS"},
                    )
                    self._snapshot = bootstrap
                    logger.info("Seeded Redis Discord access policy from DISCORD_ADMIN_GUILD_IDS")
            self._store_ready = True
            self._last_error = None
        except Exception as exc:
            self._redis_available = False
            self._store_ready = False
            self._last_error = str(exc)
            self._snapshot = self._empty_snapshot("redis_error")
            logger.exception("Failed to initialize Discord MCP access policy; denying all guilds")
        return self.status()

    async def reload(self) -> dict[str, Any]:
        """Reload Redis policy and atomically swap the snapshot only on success."""
        if self._redis is None:
            return {"success": False, "message": "Redis policy store is not configured", "policy": self.status()}
        async with self._mutation_lock:
            previous = self._snapshot
            try:
                await self._redis.ping()
                raw = await self._redis.get(self.policy_key)
                candidate = (
                    self._snapshot_from_payload(raw, "redis")
                    if raw is not None
                    else self._empty_snapshot("redis_empty")
                )
                self._snapshot = candidate
                self._redis_available = True
                self._store_ready = True
                self._last_error = None
                return {"success": True, "policy": self.status()}
            except Exception as exc:
                self._snapshot = previous
                self._redis_available = False
                self._last_error = str(exc)
                logger.exception("Failed to reload Discord MCP access policy")
                return {"success": False, "message": f"Policy reload failed: {exc}", "policy": self.status()}

    async def _load_authoritative_snapshot(self) -> PolicySnapshot:
        if self._redis is None:
            raise RuntimeError("Redis policy store is not configured")
        raw = await self._redis.get(self.policy_key)
        if raw is None:
            return self._empty_snapshot("redis_empty")
        return self._snapshot_from_payload(raw, "redis")

    async def allow_guild(
        self,
        guild_id: int,
        *,
        caller_context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if guild_id <= 0:
            return {"success": False, "message": "guild_id must be a positive integer"}
        if not self.writes_enabled:
            return {
                "success": False,
                "message": "Discord access-policy writes are disabled by deployment policy (MCP_POLICY_WRITES_ENABLED=false)",
                "policy": self.status(),
            }

        async with self._mutation_lock:
            try:
                previous = await self._load_authoritative_snapshot()
                if previous.allows(guild_id):
                    return {"success": True, "changed": False, "policy": self.status()}
                guilds = dict(previous.guilds)
                guilds[guild_id] = frozenset()
                new = PolicySnapshot(
                    version=POLICY_VERSION,
                    revision=max(previous.revision, 0) + 1,
                    all_guilds=previous.all_guilds,
                    guilds=MappingProxyType(guilds),
                    source="redis_runtime",
                )
                await self._persist_with_audit(
                    action="allow_guild",
                    guild_id=guild_id,
                    previous=previous,
                    new=new,
                    caller_context=caller_context,
                )
                self._snapshot = new
                self._redis_available = True
                self._store_ready = True
                self._last_error = None
                return {"success": True, "changed": True, "policy": self.status()}
            except Exception as exc:
                self._last_error = str(exc)
                logger.exception("Failed to allow guild %s in Discord MCP policy", guild_id)
                return {"success": False, "message": f"Policy mutation failed: {exc}", "policy": self.status()}

    async def remove_guild(
        self,
        guild_id: int,
        *,
        caller_context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if guild_id <= 0:
            return {"success": False, "message": "guild_id must be a positive integer"}
        if not self.writes_enabled:
            return {
                "success": False,
                "message": "Discord access-policy writes are disabled by deployment policy (MCP_POLICY_WRITES_ENABLED=false)",
                "policy": self.status(),
            }

        async with self._mutation_lock:
            try:
                previous = await self._load_authoritative_snapshot()
                if guild_id not in previous.guilds:
                    return {"success": True, "changed": False, "policy": self.status()}
                guilds = dict(previous.guilds)
                del guilds[guild_id]
                new = PolicySnapshot(
                    version=POLICY_VERSION,
                    revision=max(previous.revision, 0) + 1,
                    all_guilds=previous.all_guilds,
                    guilds=MappingProxyType(guilds),
                    source="redis_runtime",
                )
                await self._persist_with_audit(
                    action="remove_guild",
                    guild_id=guild_id,
                    previous=previous,
                    new=new,
                    caller_context=caller_context,
                )
                self._snapshot = new
                self._redis_available = True
                self._store_ready = True
                self._last_error = None
                return {"success": True, "changed": True, "policy": self.status()}
            except Exception as exc:
                self._last_error = str(exc)
                logger.exception("Failed to remove guild %s from Discord MCP policy", guild_id)
                return {"success": False, "message": f"Policy mutation failed: {exc}", "policy": self.status()}

    async def close(self) -> None:
        if self._redis is not None:
            close = getattr(self._redis, "aclose", None)
            if close is not None:
                await close()
            self._redis = None
        self._redis_available = False
        self._store_ready = False


access_policy_service = AccessPolicyService()

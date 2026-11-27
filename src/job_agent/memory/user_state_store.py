from __future__ import annotations

import json
import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from job_agent.memory.contracts import (
    DEFAULT_USER_STATE_PATH,
    MemoryRecord,
    MemorySource,
    PreferenceUpdateResult,
    UserState,
)


class UserStateVersionError(ValueError):
    pass


class MemoryPolicyError(ValueError):
    pass


_CREDENTIAL_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*\S+"
)


class UserStateStore:
    """Atomic, fresh-read JSON store with an explicit user namespace."""

    def __init__(
        self,
        path: Path | str = DEFAULT_USER_STATE_PATH,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.path = Path(path)
        self._now = now

    def load(self, *, user_id: str) -> UserState:
        users = self._read_users()
        payload = users.get(user_id)
        if payload is None:
            return UserState(user_id=user_id)
        return UserState.model_validate(payload)

    def save(
        self,
        *,
        user_id: str,
        state: UserState,
        expected_version: int | None = None,
    ) -> UserState:
        if state.user_id != user_id:
            raise ValueError("state user_id does not match requested namespace")
        for record in state.memories:
            if _CREDENTIAL_PATTERN.search(record.content):
                raise MemoryPolicyError("credential-like content must not be written to memory")
        users = self._read_users()
        current = UserState.model_validate(users[user_id]) if user_id in users else UserState(user_id=user_id)
        if expected_version is not None and current.version != expected_version:
            raise UserStateVersionError(
                f"user state version mismatch: expected {expected_version}, found {current.version}"
            )
        saved = state.model_copy(update={"version": current.version + 1})
        users[user_id] = saved.model_dump(mode="json")
        self._write_users(users)
        return self.load(user_id=user_id)

    def delete(self, *, user_id: str) -> None:
        users = self._read_users()
        if user_id not in users:
            return
        del users[user_id]
        if not users:
            if self.path.exists():
                self.path.unlink()
            return
        self._write_users(users)

    def update_job_location_preference(
        self,
        *,
        user_id: str,
        add_acceptable_cities: Sequence[str] = (),
        replace_preferred_city: str | None = None,
        statement: str,
        idempotency_key: str,
    ) -> PreferenceUpdateResult:
        statement = statement.strip()
        idempotency_key = idempotency_key.strip()
        if not statement or not idempotency_key:
            raise ValueError("statement and idempotency_key are required")
        current = self.load(user_id=user_id)
        prior_attempt = next(
            (
                record
                for record in current.memories
                if record.idempotency_key == idempotency_key
            ),
            None,
        )
        if prior_attempt is not None:
            return PreferenceUpdateResult(
                state=current,
                memory=prior_attempt,
                superseded_memory_id=prior_attempt.supersedes_memory_id,
                changed=False,
            )

        preferred = (
            replace_preferred_city.strip()
            if isinstance(replace_preferred_city, str)
            else str(current.preferences.get("preferred_city", "")).strip()
        )
        acceptable = _normalized_cities(
            current.preferences.get("acceptable_cities", []),
            add_acceptable_cities,
        )
        acceptable = [city for city in acceptable if city != preferred]
        if not preferred and not acceptable:
            raise ValueError("location update must contain a preferred or acceptable city")

        timestamp = self._now().isoformat()
        active = [
            record
            for record in current.memories
            if record.kind == "preference"
            and record.key == "job_location"
            and record.superseded_by_memory_id is None
        ]
        previous = active[-1] if active else None
        digest = hashlib.sha256(
            f"{user_id}\x1fjob_location\x1f{idempotency_key}".encode("utf-8")
        ).hexdigest()[:24]
        memory_id = f"memory-{digest}"
        updated_memories = [
            (
                record.model_copy(
                    update={
                        "superseded_by_memory_id": memory_id,
                        "superseded_at": timestamp,
                        "updated_at": timestamp,
                    }
                )
                if previous is not None and record.memory_id == previous.memory_id
                else record
            )
            for record in current.memories
        ]
        record = MemoryRecord(
            memory_id=memory_id,
            user_id=user_id,
            kind="preference",
            key="job_location",
            value={
                "preferred_city": preferred or None,
                "acceptable_cities": acceptable,
            },
            content=statement,
            source=MemorySource.USER_STATED,
            confidence=1.0,
            created_at=timestamp,
            updated_at=timestamp,
            supersedes_memory_id=(previous.memory_id if previous is not None else None),
            idempotency_key=idempotency_key,
        )
        preferences = dict(current.preferences)
        if preferred:
            preferences["preferred_city"] = preferred
        preferences["acceptable_cities"] = acceptable
        state = current.model_copy(
            update={
                "preferences": preferences,
                "memories": [*updated_memories, record],
                "meta": {**current.meta, "updated_at": timestamp},
            }
        )
        saved = self.save(
            user_id=user_id,
            state=state,
            expected_version=current.version,
        )
        return PreferenceUpdateResult(
            state=saved,
            memory=record,
            superseded_memory_id=(previous.memory_id if previous is not None else None),
            changed=True,
        )

    def _read_users(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("users"), dict):
            return {str(key): dict(value) for key, value in payload["users"].items()}
        if isinstance(payload, dict) and "user" in payload:
            legacy = dict(payload)
            legacy.setdefault("user_id", "default-user")
            legacy.setdefault("version", 1)
            legacy.setdefault("memories", [])
            legacy.setdefault("meta", {})
            return {"default-user": legacy}
        raise ValueError("invalid user state document")

    def _write_users(self, users: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {"version": 1, "users": users}
        try:
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temp_path.replace(self.path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
        json.loads(self.path.read_text(encoding="utf-8"))


def _normalized_cities(*values: Any) -> list[str]:
    result: list[str] = []
    for value in values:
        items = value if isinstance(value, (list, tuple, set)) else [value]
        for item in items:
            if not isinstance(item, str):
                continue
            city = item.strip()
            if city and city not in result:
                result.append(city)
    return result

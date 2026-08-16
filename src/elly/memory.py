"""Confirmed-profile and retention services (M6, DATA-002/005)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from .domain.errors import EllyError, InputInvalidError

if TYPE_CHECKING:
    from .ports.clock import ClockPort
    from .ports.repository import SessionRepositoryPort


@dataclass(frozen=True, slots=True)
class ProfileItem:
    item_id: str
    key: str
    value: str
    source: str
    sensitivity: str
    confirmed: bool
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.item_id.strip() or not self.key.strip() or not self.value.strip():
            raise InputInvalidError("profile item requires id, key, and value")
        if self.sensitivity not in {"local", "remote_allowed", "restricted"}:
            raise InputInvalidError("profile sensitivity is invalid")
        if not self.confirmed:
            raise InputInvalidError("only confirmed profile items may be stored")


class ProfileService:
    """Thin policy facade; inferred/model-derived values have no write method."""

    def __init__(self, repository: "SessionRepositoryPort", clock: "ClockPort") -> None:
        self.repository = repository
        self.clock = clock
        self.degraded = False

    def add(
        self,
        *,
        item_id: str,
        key: str,
        value: str,
        sensitivity: str = "local",
        expires_at: datetime | None = None,
    ) -> ProfileItem:
        now = self.clock.now()
        item = ProfileItem(
            item_id, key, value, "owner_confirmed", sensitivity, True, now, now, expires_at
        )
        self.repository.add_profile_item(item)
        return item

    def list(self) -> tuple[ProfileItem, ...]:
        self.repository.purge_expired_profile(self.clock.now())
        return tuple(self.repository.list_profile_items())

    def load_startup(self) -> tuple[ProfileItem, ...]:
        """Load confirmed profile data, quarantining only a corrupt profile store."""
        try:
            return self.list()
        except (EllyError, ValueError, TypeError) as exc:
            suffix = self.repository.quarantine_profile_store(self.clock.now())
            self.degraded = True
            logging.getLogger("elly.memory").warning(
                "profile store quarantined suffix=%s reason=%s", suffix, type(exc).__name__
            )
            return ()

    def correct(
        self, item_id: str, *, key: str, value: str, sensitivity: str | None = None
    ) -> ProfileItem:
        current = self.repository.get_profile_item(item_id)
        if current is None:
            raise InputInvalidError("profile item not found")
        now = self.clock.now()
        item = ProfileItem(
            item_id,
            key,
            value,
            current.source,
            sensitivity or current.sensitivity,
            True,
            current.created_at,
            now,
            current.expires_at,
        )
        self.repository.update_profile_item(item)
        return item

    def delete(self, item_id: str) -> bool:
        return self.repository.delete_profile_item(item_id, self.clock.now())

    def context_items(self) -> tuple[ProfileItem, ...]:
        return tuple(
            item for item in self.list() if item.confirmed and item.sensitivity != "restricted"
        )

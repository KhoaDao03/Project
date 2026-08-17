"""Profile item, tombstone, expiry, and quarantine persistence."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from elly.domain.errors import StorageFailureError
from elly.memory import ProfileItem

from .codecs import _iso, _parse
from .connection import _SerializedConnection
from .schema import _PROFILE_TABLES


class _ProfileStore:
    """Internal profile persistence surface mixed into the façade."""

    _conn: _SerializedConnection
    def add_profile_item(self, item: ProfileItem) -> None:
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO profile_items(item_id,key,value,source,sensitivity,confirmed,created_at,updated_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        item.item_id,
                        item.key,
                        item.value,
                        item.source,
                        item.sensitivity,
                        1,
                        _iso(item.created_at),
                        _iso(item.updated_at),
                        _iso(item.expires_at) if item.expires_at else None,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise StorageFailureError("profile item already exists") from exc
        except sqlite3.Error as exc:
            raise StorageFailureError(f"add profile failed: {type(exc).__name__}") from exc

    def list_profile_items(self) -> list[ProfileItem]:
        try:
            rows = self._conn.execute(
                "SELECT item_id,key,value,source,sensitivity,confirmed,created_at,updated_at,expires_at FROM profile_items ORDER BY key,item_id"
            ).fetchall()
            return [
                ProfileItem(
                    r[0],
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    bool(r[5]),
                    _parse(r[6]),
                    _parse(r[7]),
                    _parse(r[8]) if r[8] else None,
                )
                for r in rows
            ]
        except sqlite3.Error as exc:
            raise StorageFailureError(f"list profile failed: {type(exc).__name__}") from exc

    def get_profile_item(self, item_id: str) -> ProfileItem | None:
        return next((item for item in self.list_profile_items() if item.item_id == item_id), None)

    def update_profile_item(self, item: ProfileItem) -> None:
        try:
            with self._conn:
                cursor = self._conn.execute(
                    "UPDATE profile_items SET key=?,value=?,sensitivity=?,updated_at=?,expires_at=? WHERE item_id=?",
                    (
                        item.key,
                        item.value,
                        item.sensitivity,
                        _iso(item.updated_at),
                        _iso(item.expires_at) if item.expires_at else None,
                        item.item_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StorageFailureError("profile item not found")
        except sqlite3.Error as exc:
            raise StorageFailureError(f"update profile failed: {type(exc).__name__}") from exc

    def delete_profile_item(self, item_id: str, at: datetime) -> bool:
        try:
            with self._conn:
                cursor = self._conn.execute("DELETE FROM profile_items WHERE item_id=?", (item_id,))
                if cursor.rowcount:
                    self._conn.execute(
                        "INSERT OR REPLACE INTO profile_tombstones(item_id,deleted_at) VALUES (?,?)",
                        (item_id, _iso(at)),
                    )
                    return True
                return False
        except sqlite3.Error as exc:
            raise StorageFailureError(f"delete profile failed: {type(exc).__name__}") from exc

    def purge_expired_profile(self, now: datetime) -> int:
        try:
            with self._conn:
                cursor = self._conn.execute(
                    "DELETE FROM profile_items WHERE expires_at IS NOT NULL AND expires_at <= ?",
                    (_iso(now),),
                )
                return cursor.rowcount
        except sqlite3.Error as exc:
            raise StorageFailureError(f"purge profile failed: {type(exc).__name__}") from exc

    def quarantine_profile_store(self, at: datetime) -> str:
        """Move corrupt profile tables aside and recreate empty profile tables.

        Only profile tables are isolated; sessions, tasks, audit records, and
        versioned behavior remain available. The quarantine name contains only
        UTC digits, so it is safe to interpolate as an SQLite identifier.
        """
        suffix = at.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        try:
            with self._conn:
                for name, create_sql in _PROFILE_TABLES.items():
                    exists = self._conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
                    ).fetchone()
                    if exists:
                        quarantine = f"{name}_quarantine_{suffix}"
                        self._conn.execute(f'ALTER TABLE "{name}" RENAME TO "{quarantine}"')
                    self._conn.execute(create_sql)
            return suffix
        except sqlite3.Error as exc:
            raise StorageFailureError(f"profile quarantine failed: {type(exc).__name__}") from exc


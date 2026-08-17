"""Public SQLite repository façade.

The façade owns the database connection and composes the internal persistence
responsibilities.  The import path is intentionally stable; the implementation
modules under ``elly.adapters.sqlite`` are private and share this one
repository-owned serialized connection.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..domain.errors import StorageFailureError
from .sqlite.codecs import (
    _iso,
    _parse,
    _task_result_from_payload,
    _task_result_payload,
)
from .sqlite.connection import _ConnectionLifecycle, _SerializedConnection
from .sqlite.metadata import _MetadataStore
from .sqlite.plans import _PlanStore
from .sqlite.profile import _ProfileStore
from .sqlite.schema import (
    _MIGRATION_V1,
    _MIGRATION_V2,
    _MIGRATION_V2_STATEMENTS,
    _MIGRATION_V3,
    _MIGRATION_V3_STATEMENTS,
    _MIGRATION_V4,
    _MIGRATION_V4_STATEMENTS,
    _MIGRATION_V5,
    _MIGRATION_V5_STATEMENTS,
    _MIGRATION_V6,
    _MIGRATION_V6_STATEMENTS,
    _MIGRATION_V7,
    _MIGRATION_V7_STATEMENTS,
    _PROFILE_TABLES,
    _SAFE_EVENT_CODE,
    _SCHEMA_VERSION,
)
from .sqlite.schema import (
    apply_migrations as _apply_migrations,
)
from .sqlite.sessions import _SessionTaskStore


class SqliteSessionRepository(
    _ConnectionLifecycle,
    _PlanStore,
    _SessionTaskStore,
    _ProfileStore,
    _MetadataStore,
):
    """SQLite-backed session, plan, metadata, and profile repository."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        try:
            if db_path != ":memory:":
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(db_path, check_same_thread=False)
            self._conn = _SerializedConnection(connection)
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
        except sqlite3.Error as exc:  # pragma: no cover - construction failure is rare
            raise StorageFailureError(f"cannot open database: {type(exc).__name__}") from exc

    def apply_migrations(self) -> None:
        """Apply the stable V1–V7 schema using this repository's connection."""
        _apply_migrations(
            self._conn,
            migration_v1=_MIGRATION_V1,
            migrations=(
                (2, _MIGRATION_V2_STATEMENTS),
                (3, _MIGRATION_V3_STATEMENTS),
                (4, _MIGRATION_V4_STATEMENTS),
                (5, _MIGRATION_V5_STATEMENTS),
                (6, _MIGRATION_V6_STATEMENTS),
                (7, _MIGRATION_V7_STATEMENTS),
            ),
        )


__all__ = [
    "SqliteSessionRepository",
    "_MIGRATION_V1",
    "_MIGRATION_V2",
    "_MIGRATION_V2_STATEMENTS",
    "_MIGRATION_V3",
    "_MIGRATION_V3_STATEMENTS",
    "_MIGRATION_V4",
    "_MIGRATION_V4_STATEMENTS",
    "_MIGRATION_V5",
    "_MIGRATION_V5_STATEMENTS",
    "_MIGRATION_V6",
    "_MIGRATION_V6_STATEMENTS",
    "_MIGRATION_V7",
    "_MIGRATION_V7_STATEMENTS",
    "_PROFILE_TABLES",
    "_SAFE_EVENT_CODE",
    "_SCHEMA_VERSION",
    "_SerializedConnection",
    "_iso",
    "_parse",
    "_task_result_from_payload",
    "_task_result_payload",
]

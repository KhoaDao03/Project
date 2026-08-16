"""M6 backup/restore and retention operations (OPS-004)."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .domain.errors import ConfigInvalidError, StorageFailureError


class BackupService:
    """Authenticated encrypted backup using an owner-supplied key.

    This stdlib implementation uses an HMAC-authenticated SHA-256 keystream for
    the prototype backup envelope. It is deliberately isolated so a platform KMS
    or vetted crypto library can replace it before production.
    """

    MAGIC = b"ELLY-BACKUP-1\0"

    def __init__(self, *, db_path: str, key: str | None = None) -> None:
        self.db_path = db_path
        self.key = (key if key is not None else os.environ.get("ELLY_BACKUP_KEY", "")).encode()
        if not self.key:
            raise ConfigInvalidError("backup key is not configured")

    def create(self, destination: str) -> str:
        """Checkpoint SQLite and write an authenticated prototype backup envelope."""
        if self.db_path == ":memory:":
            raise StorageFailureError("in-memory databases cannot be backed up")
        source = Path(self.db_path)
        if not source.exists():
            raise StorageFailureError("database does not exist")
        # SQLite WAL data may not yet be in the main file. Checkpoint before
        # taking a byte-for-byte backup so recent profile/session records are
        # included even while the application connection remains open.
        try:
            checkpoint = sqlite3.connect(self.db_path)
            try:
                checkpoint.execute("PRAGMA wal_checkpoint(FULL)")
            finally:
                checkpoint.close()
        except sqlite3.Error as exc:
            raise StorageFailureError("database checkpoint failed") from exc
        raw = source.read_bytes()
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(self._seal(raw))
        return destination

    def restore(self, backup_path: str) -> None:
        """Authenticate and integrity-check a backup before replacing the DB file."""
        if self.db_path == ":memory:":
            raise StorageFailureError("in-memory databases cannot be restored")
        try:
            raw = self._open(Path(backup_path).read_bytes())
            temp = Path(str(self.db_path) + ".restore.tmp")
            temp.write_bytes(raw)
            try:
                check = sqlite3.connect(temp)
                try:
                    result = check.execute("PRAGMA integrity_check").fetchone()[0]
                    if result != "ok":
                        raise StorageFailureError("backup integrity check failed")
                finally:
                    check.close()
            finally:
                temp.unlink(missing_ok=True)
            Path(self.db_path).write_bytes(raw)
        except (OSError, sqlite3.Error, ValueError) as exc:
            raise StorageFailureError("backup restore failed") from exc

    def create_daily_if_due(self, backup_dir: str, *, now: datetime | None = None) -> str | None:
        """Create at most one automatic backup per UTC day."""
        destination_dir = Path(backup_dir)
        marker = destination_dir / ".last-successful-backup"
        today = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date().isoformat()
        try:
            if marker.exists() and marker.read_text().strip() == today:
                return None
            destination = destination_dir / f"elly-{today}.backup"
            result = self.create(str(destination))
            destination_dir.mkdir(parents=True, exist_ok=True)
            marker.write_text(today + "\n")
            return result
        except OSError as exc:
            raise StorageFailureError("automatic backup failed") from exc

    def _seal(self, raw: bytes) -> bytes:
        nonce = secrets.token_bytes(16)
        ciphertext = _xor_stream(raw, self.key, nonce)
        tag = hmac.new(self.key, nonce + ciphertext, hashlib.sha256).digest()
        return self.MAGIC + nonce + tag + ciphertext

    def _open(self, blob: bytes) -> bytes:
        if not blob.startswith(self.MAGIC) or len(blob) < len(self.MAGIC) + 48:
            raise StorageFailureError("invalid backup envelope")
        offset = len(self.MAGIC)
        nonce, tag, ciphertext = (
            blob[offset : offset + 16],
            blob[offset + 16 : offset + 48],
            blob[offset + 48 :],
        )
        expected = hmac.new(self.key, nonce + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise StorageFailureError("backup authentication failed")
        return _xor_stream(ciphertext, self.key, nonce)


def _xor_stream(data: bytes, key: bytes, nonce: bytes) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < len(data):
        block = hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        output.extend(block)
        counter += 1
    return bytes(a ^ b for a, b in zip(data, output))

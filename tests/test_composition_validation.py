"""Startup validation tests for required application dependencies."""

from __future__ import annotations

from datetime import datetime, timezone
import unittest

from elly.adapters.audit_log import StructuredAuditLog
from elly.adapters.fake_generalist import FakeGeneralist
from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.adapters.system_clock import FixedClock
from elly.composition import validate_required_dependencies
from elly.domain.errors import ConfigInvalidError

UTC = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


class CompositionValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = SqliteSessionRepository(":memory:")
        self.repository.apply_migrations()
        self.addCleanup(self.repository.close)

    def test_compatible_required_ports_validate(self) -> None:
        validate_required_dependencies(
            clock=FixedClock(UTC),
            generalist=FakeGeneralist(),
            repository=self.repository,
            audit=StructuredAuditLog(),
        )

    def test_incompatible_required_port_fails_early(self) -> None:
        with self.assertRaisesRegex(ConfigInvalidError, "required dependency generalist"):
            validate_required_dependencies(
                clock=FixedClock(UTC),
                generalist=object(),  # type: ignore[arg-type]
                repository=self.repository,
                audit=StructuredAuditLog(),
            )


if __name__ == "__main__":
    unittest.main()

"""Security-sensitive defaults: audit redaction (SEC-007 / DATA-004 initial)."""

from __future__ import annotations

import logging
import unittest
from datetime import datetime, timezone

from elly.adapters.audit_log import StructuredAuditLog
from elly.domain.enums import Route, TaskStatus
from elly.domain.models import AuditEvent
from elly.ports.audit import AuditPort

UTC = datetime(2026, 8, 3, tzinfo=timezone.utc)


class AuditRedactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.audit = StructuredAuditLog(logger=logging.getLogger("elly.audit.test"))

    def test_satisfies_port(self) -> None:
        self.assertIsInstance(self.audit, AuditPort)

    def test_detail_is_single_line_and_truncated(self) -> None:
        long_multiline = "line-one\nline-two " + ("x" * 500)
        self.audit.append(
            AuditEvent(
                task_id="t1",
                session_id="s1",
                event_type="task.completed",
                at=UTC,
                route=Route.LOCAL_GENERALIST,
                task_status=TaskStatus.COMPLETED,
                detail=long_multiline,
            )
        )
        stored = self.audit.by_task("t1")[0]
        self.assertNotIn("\n", stored.detail)
        self.assertLessEqual(len(stored.detail), 200)

    def test_correlation_by_task(self) -> None:
        for i in range(3):
            self.audit.append(
                AuditEvent(task_id="tX", session_id="s1", event_type=f"e{i}", at=UTC)
            )
        self.assertEqual(len(self.audit.by_task("tX")), 3)
        self.assertEqual(self.audit.by_task("other"), [])

    def test_log_line_excludes_detail_body(self) -> None:
        # The emitted structured log must not contain a raw (secret-bearing) detail.
        canary = "CANARY-SEKRET-9d2f"
        with self.assertLogs("elly.audit.test", level="INFO") as captured:
            self.audit.append(
                AuditEvent(task_id="t2", session_id="s1", event_type="x", at=UTC, detail=canary)
            )
        joined = "\n".join(captured.output)
        self.assertNotIn(canary, joined)  # allowlisted fields only; detail not logged


if __name__ == "__main__":
    unittest.main()

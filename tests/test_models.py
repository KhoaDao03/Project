"""Structural readiness: contract-model validation (DESIGN §6.2–6.4)."""

from __future__ import annotations

import unittest
from dataclasses import fields
from datetime import datetime, timezone

from elly.domain.enums import (
    CloudMode,
    EpistemicStatus,
    PersistenceMode,
    Route,
    TaskStatus,
    ValidationStatus,
)
from elly.domain.errors import InputInvalidError
from elly.domain.models import AuditEvent, Message, TaskRequest, TaskResult

UTC_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


class TaskRequestTests(unittest.TestCase):
    def _make(self, **over: object) -> TaskRequest:
        base = dict(
            request_id="req-1",
            session_id="sess-1",
            text="hello",
            cloud_mode=CloudMode.LOCAL_ONLY,
            persistence_mode=PersistenceMode.STORE_WITH_RETENTION,
            submitted_at=UTC_NOW,
        )
        base.update(over)
        return TaskRequest(**base)  # type: ignore[arg-type]

    def test_valid(self) -> None:
        self.assertEqual(self._make().text, "hello")

    def test_empty_text_rejected(self) -> None:
        with self.assertRaises(InputInvalidError):
            self._make(text="   ")

    def test_naive_datetime_rejected(self) -> None:
        with self.assertRaises(InputInvalidError):
            self._make(submitted_at=datetime(2026, 8, 3, 12, 0))


class TaskResultTests(unittest.TestCase):
    def test_empty_answer_allowed_only_for_failure(self) -> None:
        # blocked with empty answer is fine
        TaskResult(
            task_id="t1",
            task_status=TaskStatus.BLOCKED,
            epistemic_status=EpistemicStatus.BLOCKED,
            validation_status=ValidationStatus.REJECTED,
            answer="",
            route_summary=Route.LOCAL_GENERALIST,
        )
        # completed with empty answer is a contract violation
        with self.assertRaises(InputInvalidError):
            TaskResult(
                task_id="t1",
                task_status=TaskStatus.COMPLETED,
                epistemic_status=EpistemicStatus.INFERRED,
                validation_status=ValidationStatus.VALIDATED,
                answer="",
                route_summary=Route.LOCAL_GENERALIST,
            )


class AuditEventPrivacyTests(unittest.TestCase):
    def test_audit_event_has_no_body_field(self) -> None:
        # SEC-007/DATA-004: audit stores metadata only — no prompt/answer/body.
        names = {f.name for f in fields(AuditEvent)}
        for forbidden in ("content", "body", "prompt", "answer", "text"):
            self.assertNotIn(forbidden, names)

    def test_message_role_validated(self) -> None:
        with self.assertRaises(InputInvalidError):
            Message(role="system", content="x", created_at=UTC_NOW)


if __name__ == "__main__":
    unittest.main()

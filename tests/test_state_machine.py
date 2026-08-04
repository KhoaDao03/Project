"""Structural readiness: task state machine transitions (DESIGN §5.4)."""

from __future__ import annotations

import unittest

from elly.domain.enums import TaskStatus
from elly.domain.state_machine import (
    IllegalTransitionError,
    can_transition,
    ensure_transition,
    is_terminal,
)


class StateMachineTests(unittest.TestCase):
    def test_allowed_transitions(self) -> None:
        self.assertTrue(can_transition(TaskStatus.QUEUED, TaskStatus.RUNNING))
        self.assertTrue(can_transition(TaskStatus.RUNNING, TaskStatus.COMPLETED))
        self.assertTrue(can_transition(TaskStatus.RUNNING, TaskStatus.BLOCKED))

    def test_disallowed_transitions(self) -> None:
        self.assertFalse(can_transition(TaskStatus.COMPLETED, TaskStatus.RUNNING))
        self.assertFalse(can_transition(TaskStatus.QUEUED, TaskStatus.COMPLETED))

    def test_ensure_transition_raises_on_illegal(self) -> None:
        with self.assertRaises(IllegalTransitionError):
            ensure_transition(TaskStatus.COMPLETED, TaskStatus.RUNNING)

    def test_terminal_states(self) -> None:
        for terminal in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.CANCELLED):
            self.assertTrue(is_terminal(terminal))
        self.assertFalse(is_terminal(TaskStatus.RUNNING))


if __name__ == "__main__":
    unittest.main()

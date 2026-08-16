"""V1.5 three-axis specialist result mapping regressions."""

from __future__ import annotations

import unittest

from elly.application.response_composer import compose_specialist
from elly.domain.enums import (
    EpistemicStatus,
    OutcomeCode,
    Route,
    TaskStatus,
    ValidationStatus,
)


class SpecialistCompositionTests(unittest.TestCase):
    def test_unknown_is_not_success(self) -> None:
        result = compose_specialist(
            task_id="task-unknown",
            answer="Evidence is insufficient.",
            route=Route.RESEARCH_SPECIALIST,
            epistemic=EpistemicStatus.UNKNOWN,
        )
        self.assertIs(result.task_status, TaskStatus.COMPLETED)
        self.assertIs(result.outcome_code, OutcomeCode.UNKNOWN)
        self.assertIs(result.validation_status, ValidationStatus.QUALIFIED)

    def test_blocked_is_not_completed(self) -> None:
        result = compose_specialist(
            task_id="task-blocked",
            answer="Policy blocked this task.",
            route=Route.CODING_SPECIALIST,
            epistemic=EpistemicStatus.BLOCKED,
        )
        self.assertIs(result.task_status, TaskStatus.BLOCKED)
        self.assertIs(result.outcome_code, OutcomeCode.BLOCKED)
        self.assertIs(result.validation_status, ValidationStatus.REJECTED)

    def test_assumptions_are_not_claims(self) -> None:
        result = compose_specialist(
            task_id="task-assumption",
            answer="A qualified analysis.",
            route=Route.CODING_SPECIALIST,
            epistemic=EpistemicStatus.INFERRED,
            assumptions=("The sample is representative.",),
        )
        self.assertEqual((), result.claims)
        self.assertIn("Assumption:", result.partial_work[0])


if __name__ == "__main__":
    unittest.main()

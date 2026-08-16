"""V3 Phase 3 schema-v7 and atomic validated-plan persistence tests."""

from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import elly.adapters.sqlite_repository as sqlite_repository
from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.application.plan_builder import PlanBuilder
from elly.application.routing_contracts import CapabilityRoutingDescriptor, OperationIntentContract
from elly.domain.enums import ActionCategory
from elly.domain.errors import StorageFailureError
from elly.planning.contracts import (
    PROPOSAL_SCHEMA_VERSION,
    AuthorizationState,
    ExecutionProposal,
    FinalizationStrategy,
    PlanLimitsSnapshot,
    ProposalDisposition,
    ProposedInput,
    ProposedStep,
    StepState,
)
from elly.ports.plan_repository import PlanRepositoryPort

UTC = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
FIXTURE = Path(__file__).parent / "fixtures" / "schema_v6_representative.sql"


def _plan():
    operation = OperationIntentContract(
        operation_id="review.inspect",
        description="Inspect a bounded supplied request",
        domains=("review",),
        accepted_inputs=("text",),
        required_entities=(),
        effect=ActionCategory.NONE,
    )
    catalog = (
        CapabilityRoutingDescriptor(
            capability_id="review",
            description="Review capability",
            operations=(operation,),
        ),
    )
    proposal = ExecutionProposal(
        schema_version=PROPOSAL_SCHEMA_VERSION,
        disposition=ProposalDisposition.CAPABILITY_PLAN,
        steps=(
            ProposedStep(
                proposal_step_id="review-step",
                capability_id="review",
                operation_id="review.inspect",
                objective="inspect the supplied review request",
                objective_class="analysis",
                perspective="primary",
                inputs=(ProposedInput("text", "text"),),
            ),
        ),
        finalization=FinalizationStrategy.DIRECT,
        ambiguities=(),
        confidence=0.9,
        reason_code="TEST_PLAN",
    )
    return PlanBuilder(
        catalog,
        PlanLimitsSnapshot(max_total_timeout_seconds=120),
    ).build(proposal, "task-persist")


class Phase3PersistenceTests(unittest.TestCase):
    def test_schema_v7_is_idempotent_and_plan_repository_port_is_typed(self) -> None:
        repository = SqliteSessionRepository(":memory:")
        self.addCleanup(repository.close)
        repository.apply_migrations()
        repository.apply_migrations()
        self.assertEqual(
            7, repository._conn.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()[0]
        )
        repository.healthcheck()
        self.assertIsInstance(repository, PlanRepositoryPort)

    def test_validated_plan_round_trips_with_graph_and_state(self) -> None:
        repository = SqliteSessionRepository(":memory:")
        self.addCleanup(repository.close)
        repository.apply_migrations()
        plan = _plan()
        repository.save_plan(plan, at=UTC)
        self.assertEqual(plan, repository.get_plan(plan.plan_id))
        self.assertEqual((plan,), repository.list_plans_for_task(plan.task_id))
        row = repository._conn.execute(
            "SELECT state,authorization_state FROM plan_steps WHERE plan_id=?",
            (plan.plan_id,),
        ).fetchone()
        self.assertEqual((StepState.PENDING.value, AuthorizationState.PENDING.value), row)

    def test_duplicate_save_is_atomic_and_does_not_leave_partial_rows(self) -> None:
        repository = SqliteSessionRepository(":memory:")
        self.addCleanup(repository.close)
        repository.apply_migrations()
        plan = _plan()
        repository.save_plan(plan, at=UTC)
        with self.assertRaises(StorageFailureError):
            repository.save_plan(plan, at=UTC)
        self.assertEqual(
            (1, 1, 0),
            repository._conn.execute(
                "SELECT "
                "(SELECT COUNT(*) FROM execution_plans),"
                "(SELECT COUNT(*) FROM plan_steps),"
                "(SELECT COUNT(*) FROM plan_dependencies)"
            ).fetchone(),
        )
        self.assertEqual(1, repository.delete_plans_for_task(plan.task_id))
        self.assertIsNone(repository.get_plan(plan.plan_id))

    def test_schema_v6_fixture_upgrades_without_synthetic_plan_rows(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "schema-v6.db"
            connection = sqlite3.connect(path)
            try:
                connection.executescript(FIXTURE.read_text(encoding="utf-8"))
                connection.commit()
            finally:
                connection.close()
            repository = SqliteSessionRepository(str(path))
            self.addCleanup(repository.close)
            repository.apply_migrations()
            self.assertEqual((), repository.list_plans_for_task("v6-fixture-task"))
            self.assertIsNotNone(repository.get_task_result("v6-fixture-task"))

    def test_failed_v7_migration_rolls_back_and_leaves_schema_at_v6(self) -> None:
        repository = SqliteSessionRepository(":memory:")
        self.addCleanup(repository.close)
        repository.apply_migrations()
        for table in (
            "synthesis_results",
            "plan_events",
            "step_claim_supports",
            "step_claims",
            "step_results",
            "plan_dependencies",
            "plan_steps",
            "execution_plans",
        ):
            repository._conn.execute(f"DROP TABLE {table}")
        repository._conn.execute("UPDATE schema_meta SET version=6 WHERE id=1")
        repository._conn.commit()
        with patch.object(
            sqlite_repository,
            "_MIGRATION_V7_STATEMENTS",
            (sqlite_repository._MIGRATION_V7_STATEMENTS[0], "CREATE TABLE broken ("),
        ):
            with self.assertRaises(StorageFailureError):
                repository.apply_migrations()
        self.assertEqual(
            6, repository._conn.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()[0]
        )
        self.assertIsNone(
            repository._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_plans'"
            ).fetchone()
        )


if __name__ == "__main__":
    unittest.main()

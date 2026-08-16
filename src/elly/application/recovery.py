"""Conservative startup reconciliation for persisted execution plans."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import cast

from ..domain.enums import ActionCategory
from ..domain.errors import InputInvalidError
from ..planning.contracts import ExecutionPlan, PlanStatus, PlanStep, StepKind, StepState
from ..ports.clock import ClockPort
from ..ports.plan_repository import PlanRepositoryPort


class RecoveryDisposition(str, Enum):
    """Safe startup decision for an active persisted step."""

    RETRY_LOCAL = "retry_local"
    HOLD_UNCERTAIN_EXTERNAL = "hold_uncertain_external"
    NO_ACTION = "no_action"


@dataclass(frozen=True, slots=True)
class StepRecoveryDecision:
    """Bounded decision and target state for one persisted step."""

    step_id: str
    disposition: RecoveryDisposition
    target_state: StepState | None
    reason_code: str


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    """Safe result of reconciling one plan."""

    plan: ExecutionPlan
    decisions: tuple[StepRecoveryDecision, ...]
    resumed_step_ids: tuple[str, ...] = ()
    uncertain_step_ids: tuple[str, ...] = ()


class PlanRecovery:
    """Reconcile nonterminal plans without dispatching any provider call."""

    def __init__(self, *, clock: ClockPort | None = None) -> None:
        self._clock = clock

    @staticmethod
    def is_retryable_local(step: PlanStep) -> bool:
        """Return whether replay is local/read-only and therefore bounded-safe."""

        if not isinstance(step, PlanStep):
            raise InputInvalidError("recovery step is invalid")
        return step.kind is StepKind.LOCAL_SYNTHESIS or (
            not step.requires_external_access
            and step.effect is ActionCategory.NONE
            and not step.requires_consent
        )

    def decide(self, plan: ExecutionPlan) -> tuple[StepRecoveryDecision, ...]:
        if not isinstance(plan, ExecutionPlan):
            raise InputInvalidError("recovery plan is invalid")
        decisions: list[StepRecoveryDecision] = []
        for step in plan.steps:
            if step.state not in {StepState.AUTHORIZING, StepState.RUNNING}:
                continue
            if self.is_retryable_local(step):
                decisions.append(
                    StepRecoveryDecision(
                        step.step_id,
                        RecoveryDisposition.RETRY_LOCAL,
                        StepState.PENDING,
                        "RECOVERY_LOCAL_RETRY",
                    )
                )
            else:
                decisions.append(
                    StepRecoveryDecision(
                        step.step_id,
                        RecoveryDisposition.HOLD_UNCERTAIN_EXTERNAL,
                        StepState.INTERRUPTED,
                        "RECOVERY_EXTERNAL_OUTCOME_UNCERTAIN",
                    )
                )
        return tuple(decisions)

    def reconcile(
        self,
        plan: ExecutionPlan,
        repository: PlanRepositoryPort | None = None,
    ) -> RecoveryReport:
        """Apply decisions to storage and return the updated immutable plan."""

        if not isinstance(plan, ExecutionPlan):
            raise InputInvalidError("recovery plan is invalid")
        decisions = self.decide(plan)
        working = plan
        resumed: list[str] = []
        uncertain: list[str] = []
        for decision in decisions:
            assert decision.target_state is not None
            step = next(item for item in working.steps if item.step_id == decision.step_id)
            if repository is not None:
                reconcile_step = getattr(repository, "reconcile_step", None)
            else:
                reconcile_step = None
            if callable(reconcile_step):
                working = reconcile_step(
                    working.plan_id,
                    step.step_id,
                    decision.target_state,
                    expected_state=step.state,
                    reason_code=decision.reason_code,
                    at=self._now(),
                )
            else:
                working = replace(
                    working,
                    steps=tuple(
                        replace(item, state=decision.target_state)
                        if item.step_id == decision.step_id
                        else item
                        for item in working.steps
                    ),
                )
                self._append_event(
                    repository,
                    working.plan_id,
                    "recovery.step",
                    decision.reason_code,
                    f"step={step.step_id} state={decision.target_state.value}",
                )
            if decision.disposition is RecoveryDisposition.RETRY_LOCAL:
                resumed.append(decision.step_id)
            else:
                uncertain.append(decision.step_id)

        if uncertain and working.status in {PlanStatus.PENDING, PlanStatus.RUNNING}:
            working = self._reconcile_plan(
                working,
                PlanStatus.INTERRUPTED,
                "RECOVERY_UNCERTAIN_EXTERNAL",
                repository,
            )
        elif decisions and working.status is PlanStatus.RUNNING:
            working = self._reconcile_plan(
                working,
                PlanStatus.PENDING,
                "RECOVERY_RESUMABLE_LOCAL_WORK",
                repository,
            )
        elif not decisions and working.status is PlanStatus.RUNNING:
            # A process can stop between a plan status commit and its first
            # step transition. No provider dispatch is implied; return it to
            # the scheduler's admission state.
            working = self._reconcile_plan(
                working,
                PlanStatus.PENDING,
                "RECOVERY_NO_ACTIVE_DISPATCH",
                repository,
            )

        return RecoveryReport(
            working,
            decisions,
            tuple(resumed),
            tuple(uncertain),
        )

    def reconcile_startup(self, repository: PlanRepositoryPort) -> tuple[RecoveryReport, ...]:
        """Reconcile every pending/running plan exposed by the repository."""

        list_plans = getattr(repository, "list_nonterminal_plans", None)
        if not callable(list_plans):
            return ()
        return tuple(self.reconcile(plan, repository) for plan in list_plans())

    reconcile_nonterminal_plans = reconcile_startup

    def _reconcile_plan(
        self,
        plan: ExecutionPlan,
        status: PlanStatus,
        reason_code: str,
        repository: PlanRepositoryPort | None,
    ) -> ExecutionPlan:
        reconcile_plan = (
            getattr(repository, "reconcile_plan", None) if repository is not None else None
        )
        if callable(reconcile_plan):
            return cast(
                ExecutionPlan,
                reconcile_plan(
                    plan.plan_id,
                    status,
                    expected_status=plan.status,
                    reason_code=reason_code,
                    at=self._now(),
                ),
            )
        self._append_event(
            repository,
            plan.plan_id,
            "recovery.plan",
            reason_code,
            f"from={plan.status.value} status={status.value}",
        )
        return replace(plan, status=status)

    def _append_event(
        self,
        repository: PlanRepositoryPort | None,
        plan_id: str,
        event_type: str,
        reason_code: str,
        detail: str,
    ) -> None:
        append = getattr(repository, "append_plan_event", None) if repository is not None else None
        if callable(append):
            append(plan_id, event_type, reason_code, detail, at=self._now())

    def _now(self) -> datetime:
        if self._clock is not None:
            return self._clock.now()
        return datetime.now(timezone.utc)


__all__ = [
    "PlanRecovery",
    "RecoveryDisposition",
    "RecoveryReport",
    "StepRecoveryDecision",
]

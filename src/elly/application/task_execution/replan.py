"""Bounded, deterministic replanning for persisted V3 execution plans.

Replanning is an application policy decision, never a model instruction.  A
caller supplies a newly validated proposal candidate; this module decides
whether one replacement is allowed and then delegates all structural and
capability validation to :class:`PlanBuilder`.

The service deliberately has no provider-resolution or payload-building logic.
It can therefore approve a same-contract provider substitution without giving
the planner a provider handle, and it can retain completed results without
replaying an already-completed external operation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum

from ...domain.enums import ActionCategory
from ...domain.errors import ConfigInvalidError, InputInvalidError, PlanValidationError
from ...planning.contracts import (
    COMPILED_MAX_REPLANNING_ATTEMPTS,
    AuthorizationState,
    ExecutionPlan,
    ExecutionProposal,
    PlanStatus,
    PlanStep,
    StepState,
)
from ...ports.clock import ClockPort
from ...ports.plan_repository import PlanRepositoryPort
from ..plan_management.builder import PlanBuilder
from .cancellation import CancellationToken


class ReplanTrigger(str, Enum):
    """Typed conditions under which a replacement may be considered."""

    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    INSUFFICIENT_RESULT = "insufficient_result"
    OPTIONAL_INPUT_UNAVAILABLE = "optional_input_unavailable"
    PROVIDER_SUBSTITUTION = "provider_substitution"


@dataclass(frozen=True, slots=True)
class ReplanRequest:
    """Safe facts supplied to the deterministic replan policy.

    None of these fields contain a prompt, payload, provider body, or model
    rationale.  They are typed execution facts and bounded policy flags only.
    """

    source_plan: ExecutionPlan
    trigger: ReplanTrigger
    attempt: int = 0
    failed_step_id: str | None = None
    cancellation_accepted: bool = False
    authorization_denied: bool = False
    consent_denied: bool = False
    hard_limit_reached: bool = False
    uncertain_external_action: bool = False
    payload_expanded: bool = False
    provider_expanded: bool = False
    provider_set_expanded: bool = False
    purpose_expanded: bool = False
    side_effect_expanded: bool = False
    idempotency_safe: bool = True
    same_contract: bool = True
    replacement_capability_id: str | None = None
    replacement_operation_id: str | None = None
    completed_step_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.source_plan, ExecutionPlan):
            raise InputInvalidError("replan source plan is invalid")
        if not isinstance(self.trigger, ReplanTrigger):
            raise InputInvalidError("replan trigger is invalid")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt < 0:
            raise InputInvalidError("replan attempt must be a non-negative integer")
        for value, name in (
            (self.cancellation_accepted, "cancellation_accepted"),
            (self.authorization_denied, "authorization_denied"),
            (self.consent_denied, "consent_denied"),
            (self.hard_limit_reached, "hard_limit_reached"),
            (self.uncertain_external_action, "uncertain_external_action"),
            (self.payload_expanded, "payload_expanded"),
            (self.provider_expanded, "provider_expanded"),
            (self.provider_set_expanded, "provider_set_expanded"),
            (self.purpose_expanded, "purpose_expanded"),
            (self.side_effect_expanded, "side_effect_expanded"),
            (self.idempotency_safe, "idempotency_safe"),
            (self.same_contract, "same_contract"),
        ):
            if not isinstance(value, bool):
                raise InputInvalidError(f"replan {name} must be a bool")
        if self.failed_step_id is not None and (
            not isinstance(self.failed_step_id, str) or not self.failed_step_id.strip()
        ):
            raise InputInvalidError("replan failed_step_id is invalid")
        if self.failed_step_id is not None and not any(
            step.step_id == self.failed_step_id for step in self.source_plan.steps
        ):
            raise InputInvalidError("replan failed_step_id is not in the source plan")
        for replacement_value, replacement_name in (
            (self.replacement_capability_id, "replacement_capability_id"),
            (self.replacement_operation_id, "replacement_operation_id"),
        ):
            if replacement_value is not None and (
                not isinstance(replacement_value, str) or not replacement_value.strip()
            ):
                raise InputInvalidError(f"replan {replacement_name} is invalid")
        if not isinstance(self.completed_step_ids, tuple) or any(
            not isinstance(item, str) or not item.strip() for item in self.completed_step_ids
        ):
            raise InputInvalidError("replan completed_step_ids are invalid")
        if len(set(self.completed_step_ids)) != len(self.completed_step_ids):
            raise InputInvalidError("replan completed_step_ids must be unique")


@dataclass(frozen=True, slots=True)
class ReplanDecision:
    """The policy's bounded, display-safe decision."""

    approved: bool
    reason_code: str
    trigger: ReplanTrigger
    source_plan_id: str
    attempt: int


@dataclass(frozen=True, slots=True)
class ReplanResult:
    """Result of one policy evaluation and optional replacement creation."""

    decision: ReplanDecision
    plan: ExecutionPlan | None = None
    reused_step_ids: tuple[str, ...] = ()

    @property
    def approved(self) -> bool:
        return self.decision.approved


class ReplanPolicy:
    """Pure policy for the compiled, single-attempt replan boundary."""

    def __init__(self, *, max_attempts: int = COMPILED_MAX_REPLANNING_ATTEMPTS) -> None:
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
            raise ConfigInvalidError("replan maximum must be an integer")
        if max_attempts < 0 or max_attempts > COMPILED_MAX_REPLANNING_ATTEMPTS:
            raise ConfigInvalidError("replan maximum exceeds the compiled V3 maximum")
        self._max_attempts = max_attempts

    @property
    def max_attempts(self) -> int:
        return self._max_attempts

    def evaluate(self, request: ReplanRequest) -> ReplanDecision:
        if not isinstance(request, ReplanRequest):
            raise InputInvalidError("replan policy request is invalid")
        plan = request.source_plan

        def reject(reason_code: str) -> ReplanDecision:
            return ReplanDecision(
                False,
                reason_code,
                request.trigger,
                plan.plan_id,
                request.attempt,
            )

        if self._max_attempts == 0 or plan.limits.max_replanning_attempts == 0:
            return reject("REPLAN_DISABLED")
        if request.attempt >= self._max_attempts or plan.revision >= self._max_attempts:
            return reject("REPLAN_ATTEMPT_EXHAUSTED")
        if request.cancellation_accepted or plan.status is PlanStatus.CANCELLED:
            return reject("REPLAN_CANCELLED")
        if request.authorization_denied:
            return reject("REPLAN_AUTHORIZATION_DENIED")
        if request.consent_denied:
            return reject("REPLAN_CONSENT_DENIED")
        if request.hard_limit_reached:
            return reject("REPLAN_HARD_LIMIT_REACHED")
        if request.uncertain_external_action:
            return reject("REPLAN_EXTERNAL_OUTCOME_UNCERTAIN")
        if any(
            step.state is StepState.INTERRUPTED
            and (
                step.requires_external_access
                or step.requires_consent
                or step.effect is not ActionCategory.NONE
            )
            for step in plan.steps
        ):
            return reject("REPLAN_EXTERNAL_OUTCOME_UNCERTAIN")
        if not request.idempotency_safe:
            return reject("REPLAN_IDEMPOTENCY_UNSAFE")
        if any(
            (
                request.payload_expanded,
                request.provider_expanded,
                request.provider_set_expanded,
                request.purpose_expanded,
                request.side_effect_expanded,
            )
        ):
            return reject("REPLAN_SCOPE_EXPANSION_REQUIRES_AUTHORIZATION")
        if request.trigger is ReplanTrigger.PROVIDER_SUBSTITUTION:
            if not request.same_contract:
                return reject("REPLAN_PROVIDER_CONTRACT_CHANGED")
            failed_step = next(
                (step for step in plan.steps if step.step_id == request.failed_step_id),
                None,
            )
            if failed_step is not None:
                if (
                    request.replacement_capability_id is not None
                    and request.replacement_capability_id != failed_step.capability_id
                ):
                    return reject("REPLAN_PROVIDER_CONTRACT_CHANGED")
                if (
                    request.replacement_operation_id is not None
                    and request.replacement_operation_id != failed_step.operation_id
                ):
                    return reject("REPLAN_PROVIDER_CONTRACT_CHANGED")
        return ReplanDecision(
            True,
            "REPLAN_APPROVED",
            request.trigger,
            plan.plan_id,
            request.attempt,
        )


class ReplanService:
    """Create one validated replacement plan and retain completed artifacts."""

    def __init__(
        self,
        *,
        repository: PlanRepositoryPort,
        plan_builder: PlanBuilder,
        clock: ClockPort | None = None,
        policy: ReplanPolicy | None = None,
        catalog_provider: Callable[[], tuple[object, ...]] | None = None,
    ) -> None:
        if not isinstance(plan_builder, PlanBuilder):
            raise ConfigInvalidError("replan service requires a PlanBuilder")
        self._repository = repository
        self._plan_builder = plan_builder
        self._clock = clock
        self._policy = policy or ReplanPolicy()
        self._catalog_provider = catalog_provider

    @property
    def policy(self) -> ReplanPolicy:
        return self._policy

    def replan(
        self,
        source_plan: ExecutionPlan,
        proposal: ExecutionProposal,
        *,
        request: ReplanRequest | None = None,
        trigger: ReplanTrigger | None = None,
        failed_step_id: str | None = None,
        cancellation_accepted: bool = False,
        authorization_denied: bool = False,
        consent_denied: bool = False,
        hard_limit_reached: bool = False,
        uncertain_external_action: bool = False,
        idempotency_safe: bool = True,
        same_contract: bool = True,
        cancellation: CancellationToken | None = None,
    ) -> ReplanResult:
        if not isinstance(source_plan, ExecutionPlan):
            raise InputInvalidError("replan source plan is invalid")
        if not isinstance(proposal, ExecutionProposal):
            raise InputInvalidError("replan proposal is invalid")
        if request is None:
            if trigger is None:
                raise InputInvalidError("replan trigger is required")
            request = ReplanRequest(
                source_plan=source_plan,
                trigger=trigger,
                attempt=source_plan.revision,
                failed_step_id=failed_step_id,
                cancellation_accepted=cancellation_accepted,
                authorization_denied=authorization_denied,
                consent_denied=consent_denied,
                hard_limit_reached=hard_limit_reached,
                uncertain_external_action=uncertain_external_action,
                idempotency_safe=idempotency_safe,
                same_contract=same_contract,
            )
        elif request.source_plan.plan_id != source_plan.plan_id:
            raise InputInvalidError("replan request/source plan identity does not match")
        if cancellation is not None and not isinstance(cancellation, CancellationToken):
            raise InputInvalidError("replan cancellation token is invalid")
        if cancellation is not None and cancellation.cancelled:
            request = replace(request, cancellation_accepted=True)

        decision = self._policy.evaluate(request)
        if not decision.approved:
            self._append_event(
                source_plan.plan_id,
                "plan.replan_rejected",
                decision.reason_code,
                f"attempt={decision.attempt} trigger={decision.trigger.value}",
            )
            return ReplanResult(decision)

        catalog = (
            tuple(self._catalog_provider())
            if self._catalog_provider is not None
            else self._plan_builder.catalog
        )
        builder = PlanBuilder(
            catalog,  # type: ignore[arg-type]
            source_plan.limits,
            default_timeout_seconds=source_plan.limits.max_step_timeout_seconds,
            synthesis_timeout_seconds=source_plan.limits.max_step_timeout_seconds,
            legacy_synthesis_enabled=False,
        )
        try:
            replacement = builder.build(
                proposal,
                source_plan.task_id,
                revision=source_plan.revision + 1,
                parent_plan_id=source_plan.plan_id,
            )
        except PlanValidationError:
            self._append_event(
                source_plan.plan_id,
                "plan.replan_rejected",
                "REPLAN_VALIDATION_REJECTED",
                f"attempt={decision.attempt} trigger={decision.trigger.value}",
            )
            raise

        if request.trigger is ReplanTrigger.PROVIDER_SUBSTITUTION and request.failed_step_id:
            original = next(
                step for step in source_plan.steps if step.step_id == request.failed_step_id
            )
            revised = next(
                (step for step in replacement.steps if step.step_id == request.failed_step_id),
                None,
            )
            if (
                revised is None
                or revised.capability_id != original.capability_id
                or revised.operation_id != original.operation_id
            ):
                rejected = replace(
                    decision,
                    approved=False,
                    reason_code="REPLAN_PROVIDER_CONTRACT_CHANGED",
                )
                self._append_event(
                    source_plan.plan_id,
                    "plan.replan_rejected",
                    rejected.reason_code,
                    f"attempt={rejected.attempt} trigger={rejected.trigger.value}",
                )
                return ReplanResult(rejected)

        reusable_pairs = self._reusable_step_pairs(source_plan, replacement, request)
        reusable = tuple(new_id for _old_id, new_id in reusable_pairs)
        if reusable:
            replacement = replace(
                replacement,
                steps=tuple(
                    replace(
                        step,
                        state=StepState.COMPLETED,
                        authorization_state=next(
                            source.authorization_state
                            for source in source_plan.steps
                            if any(
                                old_id == source.step_id and new_id == step.step_id
                                for old_id, new_id in reusable_pairs
                            )
                        ),
                    )
                    if step.step_id in reusable
                    else step
                    for step in replacement.steps
                ),
            )

        save_plan = getattr(self._repository, "save_plan", None)
        if not callable(save_plan):
            raise ConfigInvalidError("repository does not implement plan persistence")
        save_plan(replacement, at=self._now())
        self._copy_completed_artifacts(source_plan, replacement, reusable_pairs)
        self._append_event(
            source_plan.plan_id,
            "plan.replanned",
            decision.reason_code,
            (
                f"replacement_plan={replacement.plan_id} revision={replacement.revision} "
                f"reused_steps={len(reusable)}"
            ),
        )
        self._append_event(
            replacement.plan_id,
            "plan.lineage",
            "REPLAN_PARENT_LINKED",
            (
                f"parent_plan={source_plan.plan_id} revision={replacement.revision} "
                f"reused_steps={len(reusable)}"
            ),
        )
        return ReplanResult(decision, replacement, reusable)

    create_replacement = replan

    @staticmethod
    def _same_step_contract(left: PlanStep, right: PlanStep) -> bool:
        return replace(
            left,
            step_id="replan-step",
            state=StepState.PENDING,
            authorization_state=AuthorizationState.PENDING,
        ) == replace(
            right,
            step_id="replan-step",
            state=StepState.PENDING,
            authorization_state=AuthorizationState.PENDING,
        )

    def _reusable_step_pairs(
        self,
        source_plan: ExecutionPlan,
        replacement: ExecutionPlan,
        request: ReplanRequest,
    ) -> tuple[tuple[str, str], ...]:
        allowed = set(request.completed_step_ids)
        get_result = getattr(self._repository, "get_step_result", None)
        get_envelope = getattr(self._repository, "get_step_envelope", None)
        reusable: list[tuple[str, str]] = []
        used_source_ids: set[str] = set()
        for step in replacement.steps:
            source = next(
                (
                    candidate
                    for candidate in source_plan.steps
                    if candidate.step_id not in used_source_ids
                    and candidate.state is StepState.COMPLETED
                    and (not allowed or candidate.step_id in allowed)
                    and self._same_step_contract(candidate, step)
                ),
                None,
            )
            if source is None:
                continue
            has_artifact = (
                callable(get_envelope)
                and get_envelope(source_plan.plan_id, source.step_id) is not None
            ) or (
                callable(get_result) and get_result(source_plan.plan_id, source.step_id) is not None
            )
            if has_artifact:
                reusable.append((source.step_id, step.step_id))
                used_source_ids.add(source.step_id)
        return tuple(reusable)

    def _copy_completed_artifacts(
        self,
        source_plan: ExecutionPlan,
        replacement: ExecutionPlan,
        reusable: tuple[tuple[str, str], ...],
    ) -> None:
        get_envelope = getattr(self._repository, "get_step_envelope", None)
        get_result = getattr(self._repository, "get_step_result", None)
        save_envelope = getattr(self._repository, "save_step_envelope", None)
        save_result = getattr(self._repository, "save_step_result", None)
        for source_step_id, replacement_step_id in reusable:
            envelope = (
                get_envelope(source_plan.plan_id, source_step_id)
                if callable(get_envelope)
                else None
            )
            if envelope is not None and callable(save_envelope):
                save_envelope(
                    replacement.plan_id,
                    replacement_step_id,
                    replace(
                        envelope,
                        plan_id=replacement.plan_id,
                        step_id=replacement_step_id,
                    ),
                    at=self._now(),
                )
                continue
            result = (
                get_result(source_plan.plan_id, source_step_id) if callable(get_result) else None
            )
            if result is not None and callable(save_result):
                save_result(replacement.plan_id, replacement_step_id, result, at=self._now())

    def _append_event(self, plan_id: str, event_type: str, reason_code: str, detail: str) -> None:
        append = getattr(self._repository, "append_plan_event", None)
        if callable(append):
            append(plan_id, event_type, reason_code, detail, at=self._now())

    def _now(self) -> datetime:
        if self._clock is not None:
            return self._clock.now()
        return datetime.now(timezone.utc)


__all__ = [
    "ReplanDecision",
    "ReplanPolicy",
    "ReplanRequest",
    "ReplanResult",
    "ReplanService",
    "ReplanTrigger",
]

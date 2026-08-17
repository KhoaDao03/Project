"""Canonical application boundary for bounded work selection and planning."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import Enum
from threading import RLock

from ..domain.enums import Route, RouteReasonCode
from ..domain.errors import InputInvalidError, PlanValidationError
from ..domain.models import RouteDecision, RouteRequest
from ..planning.contracts import (
    PROPOSAL_SCHEMA_VERSION,
    ExecutionPlan,
    ExecutionProposal,
    FinalizationStrategy,
    PlanLimitsSnapshot,
    ProposalDisposition,
    ProposedInput,
    ProposedStep,
)
from .capabilities import CapabilityRegistry
from .local_conversation_capability import (
    LOCAL_CONVERSATION_CAPABILITY_ID,
    LOCAL_CONVERSATION_OPERATION_ID,
)
from .plan_builder import PlanBuilder
from .plan_interpreter import PlanInterpreter, PlanningDecision

_DECOMPOSITION_SIGNAL = re.compile(
    r"\b(?:and then|followed by|in parallel|separately|compare|contrast)\b"
    r"|\b(?:research|search|find|look up)\b.*\b(?:and|then)\b"
    r"|\b(?:and|then)\b.*\b(?:analy[sz]e|evaluate|summari[sz]e|compare)\b",
    re.IGNORECASE,
)
_OBVIOUS_LOCAL_SIGNAL = re.compile(
    r"^\s*(?:hello|hi|hey|thanks|thank you)\b"
    r"|^\s*(?:explain|define|describe)\b"
    r"|^\s*(?:what|why|how)\s+(?:is|are|does|do|can)\b",
    re.IGNORECASE,
)


class PlanningStrategy(str, Enum):
    """Internal planning depth selected for one request."""

    DETERMINISTIC = "deterministic"
    LOCAL_LLM = "local_llm"


@dataclass(frozen=True, slots=True)
class PlanningResult:
    """One planning decision and its optional validated execution contract."""

    decision: PlanningDecision
    plan: ExecutionPlan | None
    strategy: PlanningStrategy


class PlanningService:
    """Select planning depth and return only registry-validated plans.

    The service has no execution or persistence authority. Deterministic and
    local-model planning are strategies behind this single boundary, and both
    pass capability proposals through ``PlanBuilder`` against a fresh catalog.
    """

    def __init__(
        self,
        *,
        interpreter: PlanInterpreter,
        capabilities: CapabilityRegistry,
        limits: PlanLimitsSnapshot | None = None,
        default_timeout_seconds: float = 60.0,
        response_timeout_seconds: float | None = None,
    ) -> None:
        if not isinstance(interpreter, PlanInterpreter):
            raise InputInvalidError("planning service requires a PlanInterpreter")
        if not isinstance(capabilities, CapabilityRegistry):
            raise InputInvalidError("planning service requires a CapabilityRegistry")
        self._interpreter = interpreter
        self._capabilities = capabilities
        self._limits = limits or PlanLimitsSnapshot()
        self._default_timeout_seconds = default_timeout_seconds
        self._response_timeout_seconds = response_timeout_seconds
        self._active_lock = RLock()
        self._active_tasks: set[str] = set()

    @property
    def capabilities(self) -> CapabilityRegistry:
        """Return the registry whose live catalog bounds every produced plan."""

        return self._capabilities

    def plan(
        self,
        request: RouteRequest,
        task_id: str,
        *,
        approved_context: str | None = None,
        verification_requested: bool = False,
    ) -> PlanningResult:
        """Return one decision and, when needed, a validated immutable plan."""

        if not isinstance(request, RouteRequest):
            raise InputInvalidError("planning requires a RouteRequest")
        if not isinstance(task_id, str) or not task_id.strip():
            raise InputInvalidError("planning requires a task identifier")

        deterministic = self._interpreter.deterministic_decision(request)
        strategy = self._strategy_for(request, deterministic)
        if strategy is PlanningStrategy.DETERMINISTIC:
            decision = deterministic
        else:
            with self._active_lock:
                self._active_tasks.add(task_id)
            try:
                decision = self._interpreter.interpret(
                    request,
                    approved_context=approved_context,
                )
            finally:
                with self._active_lock:
                    self._active_tasks.discard(task_id)
        decision = self._with_local_conversation_plan(decision)
        decision = self._with_local_conversation_route(decision)
        if decision.proposal.disposition is not ProposalDisposition.CAPABILITY_PLAN:
            return PlanningResult(decision, None, strategy)

        try:
            plan = self._build(
                decision.proposal,
                task_id,
                verification_requested=verification_requested,
            )
        except PlanValidationError:
            # A stricter graph rule or live-catalog race must not let planner
            # output regain routing/execution authority. Retry exactly once via
            # the deterministic strategy, then fail closed to local handling.
            fallback = self._interpreter.deterministic_decision(request)
            fallback = self._with_local_conversation_plan(fallback)
            fallback = self._with_local_conversation_route(fallback)
            if fallback.proposal.disposition is ProposalDisposition.CAPABILITY_PLAN:
                try:
                    plan = self._build(
                        fallback.proposal,
                        task_id,
                        verification_requested=verification_requested,
                    )
                    return PlanningResult(fallback, plan, PlanningStrategy.DETERMINISTIC)
                except PlanValidationError:
                    pass
            return PlanningResult(
                self._local_rejection(fallback),
                None,
                PlanningStrategy.DETERMINISTIC,
            )
        return PlanningResult(decision, plan, strategy)

    def cancel(self, task_id: str | None = None) -> bool:
        """Cancel active local-model planning globally or for one task."""

        with self._active_lock:
            active = bool(self._active_tasks) if task_id is None else task_id in self._active_tasks
        if not active:
            return False
        self._interpreter.planner.cancel()
        return True

    def _build(
        self,
        proposal: ExecutionProposal,
        task_id: str,
        *,
        verification_requested: bool,
    ) -> ExecutionPlan:
        builder = PlanBuilder(
            self._capabilities.routing_catalog(),
            self._limits,
            default_timeout_seconds=self._default_timeout_seconds,
            synthesis_timeout_seconds=self._response_timeout_seconds,
            legacy_synthesis_enabled=False,
        )
        return builder.build(
            proposal,
            task_id,
            verification_requested=verification_requested,
        )

    def _with_local_conversation_plan(
        self,
        decision: PlanningDecision,
    ) -> PlanningDecision:
        if decision.proposal.disposition not in {
            ProposalDisposition.LOCAL_ONLY,
            ProposalDisposition.UNABLE,
        }:
            return decision
        if decision.route_decision.reason_code is RouteReasonCode.ACTION_UNSUPPORTED:
            return decision
        status = self._capabilities.status(LOCAL_CONVERSATION_CAPABILITY_ID)
        if not status.available:
            return decision
        proposal = ExecutionProposal(
            schema_version=PROPOSAL_SCHEMA_VERSION,
            disposition=ProposalDisposition.CAPABILITY_PLAN,
            steps=(
                ProposedStep(
                    proposal_step_id="local-conversation",
                    capability_id=LOCAL_CONVERSATION_CAPABILITY_ID,
                    operation_id=LOCAL_CONVERSATION_OPERATION_ID,
                    objective="respond to the local conversation request",
                    objective_class="conversation",
                    perspective="local",
                    inputs=(ProposedInput("context", "context", source="context"),),
                    expected_output_type="task_result",
                ),
            ),
            finalization=FinalizationStrategy.DIRECT,
            ambiguities=(),
            confidence=decision.proposal.confidence,
            reason_code="LOCAL_CONVERSATION_PLAN",
            justification="deterministic one-step local capability plan",
        )
        return PlanningDecision(
            proposal=proposal,
            route_decision=decision.route_decision,
            accepted=decision.accepted,
            fallback_used=decision.fallback_used,
            rejection_code=decision.rejection_code,
            catalog_version=decision.catalog_version,
        )

    @staticmethod
    def _with_local_conversation_route(
        decision: PlanningDecision,
    ) -> PlanningDecision:
        """Keep the public route taxonomy stable for the local capability."""

        if (
            decision.proposal.disposition is not ProposalDisposition.CAPABILITY_PLAN
            or len(decision.proposal.steps) != 1
            or decision.proposal.steps[0].capability_id
            != LOCAL_CONVERSATION_CAPABILITY_ID
        ):
            return decision
        return replace(
            decision,
            route_decision=replace(
                decision.route_decision,
                route=Route.LOCAL_CONVERSATION,
                reason_code=RouteReasonCode.LOCAL_DEFAULT,
                # The executable identity lives in the plan step. Keep the
                # established public local-route metadata free of an optional
                # capability selection so API compatibility remains intact.
                capability_id=None,
                operation=LOCAL_CONVERSATION_OPERATION_ID,
            ),
        )

    @staticmethod
    def _strategy_for(
        request: RouteRequest,
        deterministic: PlanningDecision,
    ) -> PlanningStrategy:
        text = request.contextual_text or request.text
        if _DECOMPOSITION_SIGNAL.search(text) is not None:
            return PlanningStrategy.LOCAL_LLM
        if deterministic.proposal.disposition is not ProposalDisposition.LOCAL_ONLY:
            return PlanningStrategy.DETERMINISTIC
        if _OBVIOUS_LOCAL_SIGNAL.search(text) is not None:
            return PlanningStrategy.DETERMINISTIC
        return PlanningStrategy.LOCAL_LLM

    @staticmethod
    def _local_rejection(source: PlanningDecision) -> PlanningDecision:
        proposal = ExecutionProposal(
            schema_version=PROPOSAL_SCHEMA_VERSION,
            disposition=ProposalDisposition.LOCAL_ONLY,
            steps=(),
            finalization=FinalizationStrategy.DIRECT,
            ambiguities=(),
            confidence=1.0,
            reason_code="PLAN_VALIDATION_FALLBACK",
            justification="capability plan failed deterministic validation",
        )
        route = RouteDecision(
            route=Route.LOCAL_CONVERSATION,
            reason_code=RouteReasonCode.PROPOSAL_REJECTED,
            operation="conversation.respond",
            intent=source.route_decision.intent,
        )
        return PlanningDecision(
            proposal=proposal,
            route_decision=route,
            accepted=False,
            fallback_used=True,
            rejection_code="PLAN_VALIDATION_FAILED",
            catalog_version=source.catalog_version,
        )


__all__ = ["PlanningResult", "PlanningService", "PlanningStrategy"]

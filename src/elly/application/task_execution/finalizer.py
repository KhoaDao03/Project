"""Response-composition finalization for an executed plan."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from elly.application.response.pipeline import ResponseCompositionService, ResponsePipelineResult
from elly.application.results.plan import PlanAggregation, TemplateFinalizer
from elly.application.task_execution.cancellation import CancellationToken
from elly.domain.enums import PersistenceMode, PresentationMode
from elly.domain.models import TaskResult
from elly.planning.contracts import ExecutionPlan
from elly.ports.clock import ClockPort
from elly.ports.plan_repository import PlanRepositoryPort

from .contracts import PlanExecutionRequest


class PlanFinalizer:
    """Own terminal aggregation presentation and its recovery-safe persistence."""

    def __init__(
        self,
        *,
        repository: PlanRepositoryPort,
        response_pipeline: ResponseCompositionService,
        clock: ClockPort,
    ) -> None:
        self._repository = repository
        self._response_pipeline = response_pipeline
        self._clock = clock

    def finalize(
        self,
        aggregation: PlanAggregation,
        execution: PlanExecutionRequest,
        cancellation: CancellationToken | None = None,
    ) -> TaskResult:
        """Apply one common presentation decision after aggregation."""

        stored = self._stored_response_result(aggregation)
        if stored is not None:
            self._record_response_composition(
                aggregation.plan,
                ResponsePipelineResult(
                    result=stored,
                    mode=PresentationMode.COMPOSED,
                    observation=None,
                ),
            )
            return stored
        self._reserve_response_composition(aggregation.plan)
        composed = self._response_pipeline.compose_aggregation(
            aggregation,
            request=execution.request,
            approved_context=execution.local_context_text or execution.context_text,
            cancellation=cancellation,
        )
        self._record_response_composition(aggregation.plan, composed)
        self._save_response_composition(
            aggregation.plan,
            composed,
            retain_output=(
                execution.request.persistence_mode is PersistenceMode.STORE_WITH_RETENTION
            ),
        )
        return composed.result

    def _reserve_response_composition(self, plan: ExecutionPlan) -> None:
        save = getattr(self._repository, "save_synthesis_result", None)
        if not callable(save):
            return
        save(
            plan.plan_id,
            plan.finalization,
            "response_composition:attempting",
            (),
            {"mode": "", "outcome": "attempting", "answer": "", "answer_retained": False},
            at=self._clock.now(),
        )
        append_event = getattr(self._repository, "append_plan_event", None)
        if callable(append_event):
            append_event(
                plan.plan_id,
                "response_composer.attempted",
                "RESPONSE_COMPOSITION_RESERVED",
                "attempted=1 outcome=attempting",
                at=self._clock.now(),
            )

    def _record_response_composition(
        self,
        plan: ExecutionPlan,
        composed: ResponsePipelineResult,
    ) -> None:
        observation = composed.observation
        if observation is None:
            return
        append_event = getattr(self._repository, "append_plan_event", None)
        if not callable(append_event):
            return
        outcome = observation.outcome or "unknown"
        reason = observation.reason_code[:128]
        detail = (
            f"mode={observation.mode.value} attempted={int(observation.attempted)} "
            f"outcome={outcome} profile={observation.profile[:64]} "
            f"model={observation.model_version[:128]} "
            f"result_refs={','.join(observation.result_refs)} "
            f"claim_refs={','.join(observation.claim_refs)} "
            f"citation_refs={','.join(observation.citation_refs)} "
            f"warning_refs={','.join(observation.warning_refs)} "
            f"disagreement_refs={','.join(observation.disagreement_refs)} "
            f"record_refs={','.join(observation.immutable_record_refs)} "
            f"duration_ms={observation.duration_ms} output_tokens={observation.output_tokens}"
        )
        append_event(
            plan.plan_id,
            f"response_composer.{outcome}",
            reason or "RESPONSE_COMPOSITION_RECORDED",
            detail[:512],
            at=self._clock.now(),
        )

    def _save_response_composition(
        self,
        plan: ExecutionPlan,
        composed: ResponsePipelineResult,
        *,
        retain_output: bool,
    ) -> None:
        observation = composed.observation
        save = getattr(self._repository, "save_synthesis_result", None)
        if observation is None or not callable(save):
            return
        output: dict[str, object] = {
            "mode": observation.mode.value,
            "outcome": observation.outcome,
            "reason_code": observation.reason_code,
            "profile": observation.profile,
            "model_version": observation.model_version,
            "result_refs": list(observation.result_refs),
            "claim_refs": list(observation.claim_refs),
            "citation_refs": list(observation.citation_refs),
            "warning_refs": list(observation.warning_refs),
            "disagreement_refs": list(observation.disagreement_refs),
            "immutable_record_refs": list(observation.immutable_record_refs),
            "duration_ms": observation.duration_ms,
            "output_tokens": observation.output_tokens,
            "answer": composed.result.answer if retain_output else "",
            "answer_retained": bool(retain_output and composed.result.answer_retained),
        }
        save(
            plan.plan_id,
            plan.finalization,
            f"response_composition:{observation.outcome}",
            observation.result_refs,
            output,
            at=self._clock.now(),
        )

    def _stored_response_result(self, aggregation: PlanAggregation) -> TaskResult | None:
        get = getattr(self._repository, "get_synthesis_result", None)
        if not callable(get):
            return None
        record = get(aggregation.plan_id)
        if record is None or not record.validation_state.startswith("response_composition:"):
            return None
        canonical = TemplateFinalizer().finalize(aggregation)
        answer = record.output.get("answer") if isinstance(record.output, Mapping) else None
        if not isinstance(answer, str) or not answer.strip():
            return canonical
        return replace(canonical, answer=answer, answer_retained=True)

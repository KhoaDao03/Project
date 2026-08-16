"""V3 Phase 7 evidence-bounded local synthesis tests."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

from elly.adapters.audit_log import StructuredAuditLog
from elly.adapters.fake_synthesis import FakeSynthesis, SynthesisFailureMode
from elly.adapters.ollama_synthesis import OllamaSynthesis
from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.adapters.system_clock import FixedClock
from elly.application.capabilities import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityExecution,
    CapabilityMatch,
    CapabilityPreparation,
    CapabilityRegistry,
    CapabilityStatus,
)
from elly.application.capability_workflow import CapabilityExecutionWorkflow
from elly.application.completion import CompletionService
from elly.application.plan_builder import PlanBuilder
from elly.application.plan_executor import PlanExecutionRequest, PlanExecutor
from elly.application.routing_contracts import (
    CapabilityKind,
    CapabilityRoutingDescriptor,
    OperationIntentContract,
)
from elly.application.step_results import StepClaim, StepResultEnvelope
from elly.application.synthesis import (
    build_synthesis_input,
    render_synthesis_text,
    validate_synthesis_draft,
)
from elly.config import LocalModelProfile, LocalModelRoleConfig
from elly.domain.enums import (
    ActionCategory,
    CloudMode,
    EpistemicStatus,
    OutcomeCode,
    PersistenceMode,
    Route,
    TaskStatus,
    ValidationStatus,
)
from elly.domain.errors import MalformedResultError
from elly.domain.models import ContextManifest, SessionRecord, TaskRequest, TaskResult
from elly.planning.contracts import (
    PLAN_SCHEMA_VERSION,
    PROPOSAL_SCHEMA_VERSION,
    AuthorizationState,
    ExecutionPlan,
    ExecutionProposal,
    FinalizationStrategy,
    PlanLimitsSnapshot,
    PlanStatus,
    PlanStep,
    ProposalDisposition,
    ProposedStep,
    StepCriticality,
    StepKind,
    StepState,
)
from elly.ports.local_synthesis import (
    SYNTHESIS_DRAFT_SCHEMA_VERSION,
    SynthesisRequest,
    decode_synthesis_draft,
)

UTC = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


def _step(
    step_id: str, *, kind: StepKind = StepKind.CAPABILITY, dependencies: tuple[str, ...] = ()
) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        kind=kind,
        capability_id="local_synthesis"
        if kind is StepKind.LOCAL_SYNTHESIS
        else f"capability-{step_id}",
        operation_id="synthesis.compose"
        if kind is StepKind.LOCAL_SYNTHESIS
        else f"operation-{step_id}",
        objective=f"run {step_id}",
        objective_class="analysis",
        perspective="primary",
        inputs=(),
        dependencies=dependencies,
        output_type="task_result",
        criticality=StepCriticality.REQUIRED,
        verification=False,
        timeout_seconds=10,
        effect=ActionCategory.NONE,
        state=StepState.PENDING,
        authorization_state=AuthorizationState.NOT_REQUIRED
        if kind is StepKind.LOCAL_SYNTHESIS
        else AuthorizationState.PENDING,
    )


def _plan() -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="plan-phase7",
        task_id="task-phase7",
        schema_version=PLAN_SCHEMA_VERSION,
        revision=0,
        parent_plan_id=None,
        steps=(
            _step("left"),
            _step("right"),
            _step("synthesis", kind=StepKind.LOCAL_SYNTHESIS, dependencies=("left", "right")),
        ),
        finalization=FinalizationStrategy.LOCAL_SYNTHESIS,
        limits=PlanLimitsSnapshot(max_specialist_executions=4, max_parallel_steps=2),
        catalog_version="catalog-phase7",
    )


def _request() -> TaskRequest:
    return TaskRequest(
        request_id="request-phase7",
        session_id="session-phase7",
        text="compare the two bounded specialist findings",
        cloud_mode=CloudMode.LOCAL_ONLY,
        persistence_mode=PersistenceMode.STORE_WITH_RETENTION,
        submitted_at=UTC,
    )


def _envelope(
    plan: ExecutionPlan, step_id: str, answer: str, citation: str, *, warning: str = ""
) -> StepResultEnvelope:
    step = next(item for item in plan.steps if item.step_id == step_id)
    return StepResultEnvelope(
        schema_version="elly.step-result.v1",
        plan_id=plan.plan_id,
        task_id=plan.task_id,
        step_id=step.step_id,
        capability_id=step.capability_id,
        operation_id=step.operation_id,
        status=TaskStatus.COMPLETED,
        summary=answer,
        answer=answer,
        claims=(StepClaim("shared-claim", answer),),
        citations=(citation,),
        warnings=(warning,) if warning else (),
    )


class SynthesisContractTests(unittest.TestCase):
    def test_two_results_are_coherent_and_preserve_claims_citations_warnings_and_conflict(
        self,
    ) -> None:
        plan = _plan()
        left = _envelope(plan, "left", "left conclusion", "source:left", warning="left limitation")
        right = _envelope(plan, "right", "right conclusion", "source:right")
        input_value, aggregation = build_synthesis_input(
            plan,
            _request(),
            "approved local context",
            {"left": left.to_task_result(), "right": right.to_task_result()},
            {"left": left, "right": right},
            {
                "left": StepState.COMPLETED,
                "right": StepState.COMPLETED,
                "synthesis": StepState.PENDING,
            },
        )
        draft = FakeSynthesis().synthesize(
            SynthesisRequest(
                request_id=input_value.request_id,
                synthesis_input=input_value,
                max_output_tokens=128,
                timeout_seconds=2,
            )
        )

        validated = validate_synthesis_draft(input_value, draft)
        rendered = render_synthesis_text(input_value, validated)

        self.assertEqual(PlanStatus.PARTIAL, input_value.plan_status)
        self.assertIn("left conclusion", rendered)
        self.assertIn("right conclusion", rendered)
        self.assertIn("source:left", rendered)
        self.assertIn("left limitation", rendered)
        self.assertIn("Disagreements:", rendered)
        self.assertIn("left conclusion | right conclusion", rendered)

    def test_unknown_references_missing_mandatory_records_and_status_elevation_fail(self) -> None:
        plan = _plan()
        left = _envelope(plan, "left", "left conclusion", "source:left", warning="left limitation")
        right = _envelope(plan, "right", "right conclusion", "source:right")
        input_value, _ = build_synthesis_input(
            plan,
            _request(),
            "approved local context",
            {"left": left.to_task_result(), "right": right.to_task_result()},
            {"left": left, "right": right},
            {
                "left": StepState.COMPLETED,
                "right": StepState.COMPLETED,
                "synthesis": StepState.PENDING,
            },
        )
        fake = FakeSynthesis()
        request = SynthesisRequest(
            request_id=input_value.request_id,
            synthesis_input=input_value,
            max_output_tokens=128,
            timeout_seconds=2,
        )
        valid = fake.synthesize(request)
        bad_reference = replace(
            valid,
            sections=(replace(valid.sections[0], claim_ids=("unknown-claim",)),)
            + valid.sections[1:],
        )
        with self.assertRaises(MalformedResultError):
            validate_synthesis_draft(input_value, bad_reference)
        with self.assertRaises(MalformedResultError):
            validate_synthesis_draft(input_value, replace(valid, included_warning_ids=()))
        with self.assertRaises(MalformedResultError):
            validate_synthesis_draft(input_value, replace(valid, status=PlanStatus.COMPLETED))
        with self.assertRaises(MalformedResultError):
            validate_synthesis_draft(
                input_value,
                replace(
                    valid,
                    sections=(replace(valid.sections[0], title="invented factual heading"),)
                    + valid.sections[1:],
                ),
            )
        invented_citation = replace(
            valid,
            sections=(replace(valid.sections[0], citation_ids=("invented-citation",)),)
            + valid.sections[1:],
        )
        with self.assertRaises(MalformedResultError):
            validate_synthesis_draft(input_value, invented_citation)
        payload = valid.to_dict()
        payload["sections"][0]["action_receipt"] = "invented-receipt"  # type: ignore[index]
        with self.assertRaises(MalformedResultError):
            decode_synthesis_draft(payload)
        self.assertEqual(SYNTHESIS_DRAFT_SCHEMA_VERSION, valid.schema_version)

    def test_ollama_adapter_uses_only_the_synthesis_role_and_structured_draft(self) -> None:
        from elly.ports.local_synthesis import (
            SYNTHESIS_INPUT_SCHEMA_VERSION,
            SynthesisInput,
            SynthesisStepSummary,
        )

        synthesis_input = SynthesisInput(
            schema_version=SYNTHESIS_INPUT_SCHEMA_VERSION,
            request_id="request-ollama",
            task_id="task-ollama",
            plan_id="plan-ollama",
            request_text="organize the result",
            approved_context="approved context",
            plan_summary="one approved step",
            plan_status=PlanStatus.COMPLETED,
            finalization=FinalizationStrategy.LOCAL_SYNTHESIS,
            step_summaries=(
                SynthesisStepSummary("result-one", "step-one", StepState.COMPLETED, "answer"),
            ),
        )
        request = SynthesisRequest("request-ollama", synthesis_input, 64, 3.0)
        draft = FakeSynthesis().synthesize(request)
        role = LocalModelRoleConfig(
            "synthesis",
            LocalModelProfile(
                "synthesis-test", "ollama", "synthesis-model", "http://127.0.0.1:11434", 5.0
            ),
            64,
        )
        adapter = OllamaSynthesis(role=role)

        class _Response:
            def read(self) -> bytes:
                return json.dumps({"response": draft.to_json()}).encode("utf-8")

            def close(self) -> None:
                return None

        captured: dict[str, Any] = {}

        def fake_urlopen(request_object: object, *, timeout: float) -> _Response:
            captured["request"] = request_object
            captured["timeout"] = timeout
            return _Response()

        with patch("elly.adapters.ollama_synthesis.urlopen", fake_urlopen):
            self.assertEqual(draft, adapter.synthesize(request))
        body = json.loads(captured["request"].data.decode("utf-8"))
        self.assertEqual("synthesis-model", body["model"])
        self.assertFalse(body["stream"])
        self.assertIn("elly.synthesis-input.v1", body["prompt"])
        self.assertNotIn("capability_registry", body["prompt"])


class _Capability:
    def __init__(self, capability_id: str) -> None:
        self.capability_id = capability_id
        operation = OperationIntentContract(
            operation_id=f"{capability_id}.run",
            description=f"Run {capability_id}",
            domains=("analysis",),
            accepted_inputs=("text",),
            required_entities=(),
            effect=ActionCategory.NONE,
        )
        self.descriptor = CapabilityDescriptor(
            capability_id=capability_id,
            description=f"{capability_id} capability",
            routes=(Route.REGISTERED_CAPABILITY,),
            request_schema="phase7-v1",
            operations=(operation.operation_id,),
            routing=CapabilityRoutingDescriptor(
                capability_id=capability_id,
                description=f"{capability_id} capability",
                operations=(operation,),
                kind=CapabilityKind.SPECIALIST,
            ),
        )

    def status(self) -> CapabilityStatus:
        return CapabilityStatus(CapabilityAvailability.AVAILABLE)

    def can_handle(self, _request: object) -> CapabilityMatch:
        return CapabilityMatch(True, "PHASE7_TEST")

    def prepare(self, _intent: object, _request: object) -> CapabilityPreparation:
        return CapabilityPreparation(True, "PHASE7_TEST")

    def execute(self, request: object) -> CapabilityExecution:
        task_id = request.task_id  # type: ignore[attr-defined]
        answer = self.capability_id
        return CapabilityExecution(
            TaskResult(
                task_id=task_id,
                task_status=TaskStatus.COMPLETED,
                epistemic_status=EpistemicStatus.INFERRED,
                validation_status=ValidationStatus.VALIDATED,
                answer=answer,
                route_summary=Route.REGISTERED_CAPABILITY,
                outcome_code=OutcomeCode.SUCCESS,
            ),
            request.context_manifest,  # type: ignore[attr-defined]
        )


class SynthesisExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = SqliteSessionRepository(":memory:")
        self.addCleanup(self.repository.close)
        self.repository.apply_migrations()
        self.repository.create_session(
            SessionRecord(
                "session-phase7", PersistenceMode.STORE_WITH_RETENTION, CloudMode.LOCAL_ONLY, UTC
            )
        )
        self.clock = FixedClock(UTC)
        self._run_count = 0

    def _run(self, synthesis: FakeSynthesis):
        self._run_count += 1
        registry = CapabilityRegistry((_Capability("left"), _Capability("right")))
        audit = StructuredAuditLog(repository=self.repository)
        workflow = CapabilityExecutionWorkflow(
            clock=self.clock,
            capability_registry=registry,
            completion=CompletionService(clock=self.clock, repository=self.repository, audit=audit),
        )
        proposal = ExecutionProposal(
            schema_version=PROPOSAL_SCHEMA_VERSION,
            disposition=ProposalDisposition.CAPABILITY_PLAN,
            steps=(
                ProposedStep(
                    "left-step",
                    "left",
                    "left.run",
                    "analyze the left perspective",
                    "analysis",
                    "primary",
                ),
                ProposedStep(
                    "right-step",
                    "right",
                    "right.run",
                    "analyze the right perspective",
                    "analysis",
                    "secondary",
                ),
            ),
            finalization=FinalizationStrategy.LOCAL_SYNTHESIS,
            ambiguities=(),
            confidence=1.0,
            reason_code="PHASE7_TEST",
        )
        plan = PlanBuilder(
            registry.routing_catalog(),
            PlanLimitsSnapshot(max_specialist_executions=4, max_parallel_steps=2),
        ).build(proposal, f"task-phase7-execution-{self._run_count}")
        self.repository.save_plan(plan, at=UTC)
        self.repository.start_task(plan.task_id, "session-phase7", UTC)
        result = PlanExecutor(
            repository=self.repository,
            capability_registry=registry,
            capability_workflow=workflow,
            clock=self.clock,
            synthesis_port=synthesis,
            synthesis_max_output_tokens=128,
            synthesis_timeout_seconds=2,
        ).execute(
            plan,
            PlanExecutionRequest(
                request=replace(_request(), request_id="request-phase7-execution"),
                context_text="approved context",
                context_manifest=ContextManifest((), {}, 32, 4),
            ),
        )
        return result, plan

    def test_synthesis_node_returns_one_final_response_and_records_validation(self) -> None:
        result, plan = self._run(FakeSynthesis())

        self.assertEqual(PlanStatus.COMPLETED, result.status)
        self.assertIn("left", result.final_result.answer)  # type: ignore[union-attr]
        self.assertIn("right", result.final_result.answer)  # type: ignore[union-attr]
        record = self.repository.get_synthesis_result(plan.plan_id)
        self.assertIsNotNone(record)
        self.assertEqual("validated", record.validation_state)  # type: ignore[union-attr]
        self.assertEqual(("result-left-step", "result-right-step"), record.referenced_result_ids)  # type: ignore[union-attr]

    def test_model_failure_and_cancellation_use_visible_deterministic_fallback(self) -> None:
        for failure in (
            SynthesisFailureMode.MALFORMED,
            SynthesisFailureMode.TIMEOUT,
            SynthesisFailureMode.CANCELLED,
        ):
            with self.subTest(failure=failure):
                result, plan = self._run(FakeSynthesis(failure=failure))
                self.assertEqual(PlanStatus.COMPLETED, result.status)
                self.assertIn("Synthesis fallback", result.final_result.answer)  # type: ignore[union-attr]
                self.assertTrue(result.final_result.failures)  # type: ignore[union-attr]
                self.assertTrue(
                    any(
                        event.event_type == "synthesis.fallback"
                        for event in self.repository.plan_events(plan.plan_id)
                    )
                )


if __name__ == "__main__":
    unittest.main()

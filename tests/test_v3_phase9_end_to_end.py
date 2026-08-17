"""Phase 9 tests for the composed public planner-to-plan workflow."""

from __future__ import annotations

import unittest
from collections.abc import Sequence
from datetime import datetime, timezone
from threading import Barrier

from elly.adapters.audit_log import StructuredAuditLog
from elly.adapters.fake_generalist import FakeGeneralist
from elly.adapters.fake_planner import FakePlanner
from elly.adapters.fake_response_composer import FakeResponseComposer
from elly.adapters.fake_synthesis import FakeSynthesis
from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.adapters.system_clock import FixedClock
from elly.api.application import EllyApplication
from elly.api.contracts import (
    ConsentDecisionRequest,
    CreateSessionRequest,
    SubmitRequest,
)
from elly.application.capabilities import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityExecution,
    CapabilityMatch,
    CapabilityPreparation,
    CapabilityRegistry,
    CapabilityStatus,
)
from elly.application.routing_contracts import (
    CapabilityKind,
    CapabilityRoutingDescriptor,
    FreshnessSupport,
    OperationIntentContract,
)
from elly.composition import Application
from elly.config import load_config
from elly.domain.enums import (
    ActionCategory,
    CloudMode,
    EpistemicStatus,
    Route,
    TaskStatus,
    ValidationStatus,
)
from elly.domain.models import ActionProposal, TaskResult
from elly.guardrails.executor import BoundedTaskExecutor
from elly.planning.contracts import (
    PROPOSAL_SCHEMA_VERSION,
    ExecutionProposal,
    FinalizationStrategy,
    ProposalDisposition,
    ProposedInput,
    ProposedStep,
)
from elly.privacy import ConsentWorkflow

UTC = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


class _Capability:
    def __init__(
        self,
        capability_id: str,
        *,
        external: bool = False,
        kind: CapabilityKind = CapabilityKind.SPECIALIST,
        execution_barrier: Barrier | None = None,
    ) -> None:
        self.calls = 0
        self.payloads: list[str] = []
        self.execution_barrier = execution_barrier
        operation = OperationIntentContract(
            operation_id=f"{capability_id}.run",
            description=f"Run {capability_id}",
            domains=("phase9",),
            accepted_inputs=("text", "task_result"),
            required_entities=(),
            output_type="task_result",
            effect=ActionCategory.NONE,
            freshness=(
                FreshnessSupport.CURRENT
                if kind is CapabilityKind.RESEARCH
                else FreshnessSupport.STATIC
            ),
        )
        self.descriptor = CapabilityDescriptor(
            capability_id=capability_id,
            description=f"{capability_id} phase nine capability",
            routes=(Route.REGISTERED_CAPABILITY,),
            request_schema="phase9-v1",
            operations=(operation.operation_id,),
            requires_external_boundary=external,
            requires_consent=external,
            destination="phase9-provider" if external else "",
            model="phase9-model" if external else "",
            purpose="phase nine verification" if external else "",
            declared_action=ActionProposal.none(),
            routing=CapabilityRoutingDescriptor(
                capability_id=capability_id,
                description=f"{capability_id} phase nine capability",
                operations=(operation,),
                kind=kind,
                requires_external_access=external,
                requires_consent=external,
            ),
        )

    def status(self) -> CapabilityStatus:
        return CapabilityStatus(CapabilityAvailability.AVAILABLE)

    def can_handle(self, _request) -> CapabilityMatch:  # type: ignore[no-untyped-def]
        return CapabilityMatch(True, "PHASE9_MATCH")

    def prepare(self, _intent, _request) -> CapabilityPreparation:  # type: ignore[no-untyped-def]
        return CapabilityPreparation(True, "PHASE9_PREPARED")

    def execute(self, request) -> CapabilityExecution:  # type: ignore[no-untyped-def]
        self.calls += 1
        self.payloads.append(request.context_text)
        if self.execution_barrier is not None:
            self.execution_barrier.wait(timeout=1.0)
        return CapabilityExecution(
            TaskResult(
                task_id=request.task_id,
                task_status=TaskStatus.COMPLETED,
                epistemic_status=EpistemicStatus.INFERRED,
                validation_status=ValidationStatus.VALIDATED,
                answer=f"completed:{self.descriptor.capability_id}",
                route_summary=Route.REGISTERED_CAPABILITY,
            ),
            request.context_manifest,
        )


def _proposal(capability_id: str) -> ExecutionProposal:
    return ExecutionProposal(
        schema_version=PROPOSAL_SCHEMA_VERSION,
        disposition=ProposalDisposition.CAPABILITY_PLAN,
        steps=(
            ProposedStep(
                proposal_step_id="analysis-step",
                capability_id=capability_id,
                operation_id=f"{capability_id}.run",
                objective="analyze the public phase nine request",
                objective_class="analysis",
                perspective="primary",
                inputs=(ProposedInput("text", "text"),),
                expected_output_type="task_result",
                requires_external_access=False,
            ),
        ),
        finalization=FinalizationStrategy.DIRECT,
        ambiguities=(),
        confidence=1.0,
        reason_code="PHASE9_COMPOSED_PLAN",
    )


def _research_synthesis_proposal(
    research_id: str,
    specialist_ids: Sequence[str],
) -> ExecutionProposal:
    research_step = ProposedStep(
        proposal_step_id="research-step",
        capability_id=research_id,
        operation_id=f"{research_id}.run",
        objective="collect current public evidence",
        objective_class="research",
        perspective="evidence",
        inputs=(ProposedInput("text", "text", source="context"),),
        expected_output_type="task_result",
        requires_current_information=True,
    )
    specialist_steps = tuple(
        ProposedStep(
            proposal_step_id=f"specialist-{index}",
            capability_id=capability_id,
            operation_id=f"{capability_id}.run",
            objective=f"analyze research from perspective {index}",
            objective_class="analysis",
            perspective=f"perspective-{index}",
            inputs=(
                ProposedInput(
                    "research",
                    "task_result",
                    source="step",
                    reference="research-step",
                ),
            ),
            dependencies=("research-step",),
            expected_output_type="task_result",
        )
        for index, capability_id in enumerate(specialist_ids, start=1)
    )
    return ExecutionProposal(
        schema_version=PROPOSAL_SCHEMA_VERSION,
        disposition=ProposalDisposition.CAPABILITY_PLAN,
        steps=(research_step,) + specialist_steps,
        finalization=FinalizationStrategy.LOCAL_SYNTHESIS,
        ambiguities=(),
        confidence=1.0,
        reason_code="PHASE9_RESEARCH_SYNTHESIS",
    )


class ComposedWorkflowTests(unittest.TestCase):
    def _application(
        self,
        capability: _Capability,
        *,
        proposal: ExecutionProposal | None = None,
        additional_capabilities: tuple[_Capability, ...] = (),
        response_composer: FakeResponseComposer | None = None,
    ) -> Application:
        repository = SqliteSessionRepository(":memory:")
        repository.apply_migrations()
        selected_proposal = proposal or _proposal(capability.descriptor.capability_id)
        return Application(
            config=load_config(None),
            clock=FixedClock(UTC, step_seconds=1),
            generalist=FakeGeneralist(),
            repository=repository,
            audit=StructuredAuditLog(repository=repository),
            capability_registry=CapabilityRegistry((capability,) + additional_capabilities),
            consent=ConsentWorkflow(),
            planner=FakePlanner(selected_proposal),
            synthesis=FakeSynthesis(),
            response_composer=response_composer,
            executor=BoundedTaskExecutor(workers=2, queue_size=4),
        )

    def test_public_submission_runs_planner_validated_plan_and_capability(self) -> None:
        capability = _Capability("phase9.analysis")
        application = self._application(capability)
        api = EllyApplication(application)
        self.addCleanup(api.close)
        session = api.create_session(CreateSessionRequest())
        assert session.value is not None

        result = api.submit_and_wait(
            SubmitRequest("phase9-e2e", session.value.session_id, "analyze this request")
        )

        self.assertTrue(result.is_success)
        assert result.value is not None
        self.assertEqual(TaskStatus.COMPLETED, result.value.status)
        self.assertEqual(1, capability.calls)
        self.assertIsNotNone(result.value.plan)
        self.assertEqual("completed:phase9.analysis", result.value.answer)

    def test_exact_consent_resumes_same_plan_revision(self) -> None:
        capability = _Capability("phase9.external", external=True)
        application = self._application(capability)
        # Match the external metadata declared by the capability proposal.
        proposal = _proposal(capability.descriptor.capability_id)
        external_step = proposal.steps[0]
        application.planner = FakePlanner(
            ExecutionProposal(
                schema_version=proposal.schema_version,
                disposition=proposal.disposition,
                steps=(
                    ProposedStep(
                        proposal_step_id=external_step.proposal_step_id,
                        capability_id=external_step.capability_id,
                        operation_id=external_step.operation_id,
                        objective=external_step.objective,
                        objective_class=external_step.objective_class,
                        perspective=external_step.perspective,
                        inputs=external_step.inputs,
                        expected_output_type=external_step.expected_output_type,
                        requires_external_access=True,
                    ),
                ),
                finalization=proposal.finalization,
                ambiguities=(),
                confidence=1.0,
                reason_code=proposal.reason_code,
            )
        )
        application.plan_interpreter = application.plan_interpreter.__class__(
            planner=application.planner,
            capabilities=application.capability_registry,
            routing_policy=application.routing_policy,
        )
        api = EllyApplication(application)
        self.addCleanup(api.close)
        session = api.create_session(
            CreateSessionRequest(cloud_mode=CloudMode.CLOUD_PERMITTED)
        )
        assert session.value is not None

        pending = api.submit_and_wait(
            SubmitRequest(
                "phase9-consent",
                session.value.session_id,
                "analyze my private record",
            )
        )
        self.assertTrue(pending.is_success)
        assert pending.value is not None
        self.assertEqual(TaskStatus.AWAITING_CONSENT, pending.value.status)
        self.assertIsNotNone(pending.value.plan)
        assert pending.value.plan is not None
        plan_id = pending.value.plan.plan_id
        revision = pending.value.plan.revision
        consents = api.list_consents()
        assert consents.value is not None
        self.assertEqual(1, len(consents.value))

        resumed = api.decide_consent(
            ConsentDecisionRequest(consents.value[0].proposal_id, True, "phase9-test")
        )

        self.assertTrue(resumed.is_success)
        assert resumed.value is not None
        self.assertEqual(TaskStatus.COMPLETED, resumed.value.status)
        self.assertIsNotNone(resumed.value.plan)
        assert resumed.value.plan is not None
        self.assertEqual(plan_id, resumed.value.plan.plan_id)
        self.assertEqual(revision, resumed.value.plan.revision)
        self.assertEqual(1, capability.calls)

    def test_research_then_specialist_runs_through_local_synthesis(self) -> None:
        research = _Capability("phase9.research", kind=CapabilityKind.RESEARCH)
        specialist = _Capability("phase9.specialist")
        proposal = _research_synthesis_proposal(
            research.descriptor.capability_id,
            (specialist.descriptor.capability_id,),
        )
        application = self._application(
            research,
            proposal=proposal,
            additional_capabilities=(specialist,),
        )
        api = EllyApplication(application)
        self.addCleanup(api.close)
        session = api.create_session(CreateSessionRequest())
        assert session.value is not None

        result = api.submit_and_wait(
            SubmitRequest(
                "phase9-research-one",
                session.value.session_id,
                "research and analyze the current public topic",
            )
        )

        self.assertTrue(result.is_success)
        assert result.value is not None
        self.assertEqual(TaskStatus.COMPLETED, result.value.status)
        self.assertEqual(1, research.calls)
        self.assertEqual(1, specialist.calls)
        self.assertIn("completed:phase9.research", specialist.payloads[0])
        self.assertIn("completed:phase9.research", result.value.answer)
        self.assertIn("completed:phase9.specialist", result.value.answer)
        assert result.value.plan is not None
        self.assertEqual(3, len(result.value.plan.steps))

    def test_research_feeds_two_specialists_then_local_synthesis(self) -> None:
        research = _Capability("phase9.research", kind=CapabilityKind.RESEARCH)
        parallel_start = Barrier(2)
        first = _Capability("phase9.specialist_one", execution_barrier=parallel_start)
        second = _Capability("phase9.specialist_two", execution_barrier=parallel_start)
        proposal = _research_synthesis_proposal(
            research.descriptor.capability_id,
            (first.descriptor.capability_id, second.descriptor.capability_id),
        )
        application = self._application(
            research,
            proposal=proposal,
            additional_capabilities=(first, second),
        )
        api = EllyApplication(application)
        self.addCleanup(api.close)
        session = api.create_session(CreateSessionRequest())
        assert session.value is not None

        result = api.submit_and_wait(
            SubmitRequest(
                "phase9-research-two",
                session.value.session_id,
                "research and compare two analyses of the current public topic",
            )
        )

        self.assertTrue(result.is_success)
        assert result.value is not None
        self.assertEqual(TaskStatus.COMPLETED, result.value.status)
        self.assertEqual((1, 1, 1), (research.calls, first.calls, second.calls))
        self.assertIn("completed:phase9.research", first.payloads[0])
        self.assertIn("completed:phase9.research", second.payloads[0])
        self.assertIn("completed:phase9.specialist_one", result.value.answer)
        self.assertIn("completed:phase9.specialist_two", result.value.answer)
        assert result.value.plan is not None
        self.assertEqual(4, len(result.value.plan.steps))

    def test_v35_multi_result_plan_uses_one_post_aggregation_composer(self) -> None:
        research = _Capability("phase9.v35_research", kind=CapabilityKind.RESEARCH)
        first = _Capability("phase9.v35_specialist_one")
        second = _Capability("phase9.v35_specialist_two")
        proposal = _research_synthesis_proposal(
            research.descriptor.capability_id,
            (first.descriptor.capability_id, second.descriptor.capability_id),
        )
        composer = FakeResponseComposer()
        application = self._application(
            research,
            proposal=proposal,
            additional_capabilities=(first, second),
            response_composer=composer,
        )
        api = EllyApplication(application)
        self.addCleanup(api.close)
        session = api.create_session(CreateSessionRequest())
        assert session.value is not None

        result = api.submit_and_wait(
            SubmitRequest(
                "phase9-v35-multi",
                session.value.session_id,
                "research and compare two analyses of the current public topic",
            )
        )

        self.assertTrue(result.is_success)
        assert result.value is not None
        self.assertEqual(TaskStatus.COMPLETED, result.value.status)
        self.assertEqual(1, len(composer.requests))
        assert result.value.plan is not None
        self.assertEqual(3, len(result.value.plan.steps))
        self.assertNotIn("synthesis", {step.step_id for step in result.value.plan.steps})
        self.assertIn("completed:phase9.v35_specialist_one", result.value.answer)
        self.assertIn("completed:phase9.v35_specialist_two", result.value.answer)


if __name__ == "__main__":
    unittest.main()

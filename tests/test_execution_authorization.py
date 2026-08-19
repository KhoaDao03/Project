"""Execution-time authorization, typed results, and boundary tests."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from elly.adapters.audit_log import StructuredAuditLog
from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.adapters.system_clock import FixedClock
from elly.application.authorization.actions import normalized_action_digest
from elly.application.authorization.consent import (
    CloudAuthorizationPolicy,
    CloudAuthorizationRequest,
)
from elly.application.capabilities.registry import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityExecution,
    CapabilityMatch,
    CapabilityPreparation,
    CapabilityRegistry,
    CapabilityRequest,
    CapabilityStatus,
)
from elly.application.capabilities.workflow import CapabilityExecutionWorkflow
from elly.application.completion import CompletionService
from elly.application.plan_management.builder import PlanBuilder
from elly.application.results.step import (
    ActionExecutionReceipt,
    EvidenceStatus,
    StepClaim,
    StepResultEnvelope,
    StepUsage,
    normalize_step_result,
)
from elly.application.routing.contracts import (
    CapabilityKind,
    CapabilityRoutingDescriptor,
    OperationIntentContract,
)
from elly.application.task_execution.cancellation import CancellationToken
from elly.application.task_execution.contracts import PlanExecutionRequest
from elly.application.task_execution.service import TaskExecutionService
from elly.domain.enums import (
    ActionCategory,
    ActionDataSensitivity,
    ActionImpactFlag,
    ActionProposalSource,
    ActionReversibility,
    ActionSideEffect,
    CloudMode,
    EpistemicStatus,
    PersistenceMode,
    Route,
    TaskStatus,
    ValidationStatus,
)
from elly.domain.errors import MalformedResultError
from elly.domain.models import (
    ActionProposal,
    ActionTarget,
    ClaimSupport,
    ContextManifest,
    SessionRecord,
    TaskRequest,
    TaskResult,
)
from elly.planning.contracts import (
    PROPOSAL_SCHEMA_VERSION,
    ExecutionProposal,
    FinalizationStrategy,
    PlanLimitsSnapshot,
    ProposalDisposition,
    ProposedInput,
    ProposedStep,
)
from elly.privacy import ConsentWorkflow, PrivacyPolicy

UTC = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


def _legacy_result(task_id: str, answer: str = "answer") -> TaskResult:
    return TaskResult(
        task_id=task_id,
        task_status=TaskStatus.COMPLETED,
        epistemic_status=EpistemicStatus.INFERRED,
        validation_status=ValidationStatus.VALIDATED,
        answer=answer,
        route_summary=Route.REGISTERED_CAPABILITY,
    )


def _plan_for(
    capability_id: str, operation_id: str, *, effect: ActionCategory = ActionCategory.NONE
):
    operation = OperationIntentContract(
        operation_id=operation_id,
        description="Run the phase five test operation",
        domains=("phase5",),
        accepted_inputs=("text",),
        required_entities=(),
        output_type="task_result",
        effect=effect,
    )
    catalog = (
        CapabilityRoutingDescriptor(
            capability_id=capability_id,
            description="Phase five test capability",
            operations=(operation,),
            kind=CapabilityKind.SPECIALIST,
        ),
    )
    proposal = ExecutionProposal(
        schema_version=PROPOSAL_SCHEMA_VERSION,
        disposition=ProposalDisposition.CAPABILITY_PLAN,
        steps=(
            ProposedStep(
                proposal_step_id="step-one",
                capability_id=capability_id,
                operation_id=operation_id,
                objective="inspect the phase five request safely",
                objective_class="analysis",
                perspective="primary",
                inputs=(ProposedInput("text", "text"),),
                expected_output_type="task_result",
            ),
        ),
        finalization=FinalizationStrategy.DIRECT,
        ambiguities=(),
        confidence=1.0,
        reason_code="TEST_PHASE5",
    )
    return PlanBuilder(catalog, PlanLimitsSnapshot(max_total_timeout_seconds=120)).build(
        proposal, "task-phase5"
    )


class _Capability:
    def __init__(
        self, *, action: ActionProposal | None = None, receipt: bool = False, raises: bool = False
    ) -> None:
        self.calls = 0
        self.receipt = receipt
        self.raises = raises
        self.action = action or ActionProposal.none()
        operation = OperationIntentContract(
            operation_id="phase5.run",
            description="Run phase five capability",
            domains=("phase5",),
            accepted_inputs=("text",),
            required_entities=(),
            output_type="task_result",
            effect=self.action.category,
        )
        self.descriptor = CapabilityDescriptor(
            capability_id="phase5.capability",
            description="Phase five capability",
            routes=(Route.REGISTERED_CAPABILITY,),
            request_schema="phase5-v1",
            operations=(operation.operation_id,),
            declared_action=self.action,
            routing=CapabilityRoutingDescriptor(
                capability_id="phase5.capability",
                description="Phase five capability",
                operations=(operation,),
            ),
        )

    def status(self) -> CapabilityStatus:
        return CapabilityStatus(CapabilityAvailability.AVAILABLE)

    def can_handle(self, _request: CapabilityRequest) -> CapabilityMatch:
        return CapabilityMatch(True, "TEST_MATCH")

    def prepare(self, _intent, _request: CapabilityRequest) -> CapabilityPreparation:  # type: ignore[no-untyped-def]
        return CapabilityPreparation(True, "TEST_PREPARED")

    def propose_action(self, _request: CapabilityRequest) -> ActionProposal:
        return self.action

    def execute(self, request: CapabilityRequest) -> CapabilityExecution:
        self.calls += 1
        if self.raises:
            raise RuntimeError("provider-native detail must not escape")
        receipt = None
        if self.receipt:
            receipt = ActionExecutionReceipt(
                receipt_id="receipt-phase5",
                action_digest=normalized_action_digest(self.action),
                capability_id=self.descriptor.capability_id,
                operation_id=request.operation,
                completed_at=UTC,
            )
        return CapabilityExecution(
            _legacy_result(
                request.task_id,
                "completed action" if self.action.is_consequential else "local result",
            ),
            request.context_manifest,
            action_receipt=receipt,
        )


class StepResultContractTests(unittest.TestCase):
    def test_legacy_result_normalizes_and_typed_result_round_trips(self) -> None:
        envelope = normalize_step_result(
            _legacy_result("task-1"),
            plan_id="plan-1",
            task_id="task-1",
            step_id="step-1",
            capability_id="phase5.capability",
            operation_id="phase5.run",
        )
        self.assertEqual("elly.step-result.v1", envelope.schema_version)
        self.assertEqual("answer", envelope.to_task_result().answer)
        self.assertEqual(envelope, StepResultEnvelope.from_dict(envelope.to_dict()))

    def test_unknown_old_and_malformed_schema_are_rejected(self) -> None:
        envelope = normalize_step_result(
            _legacy_result("task-1"),
            plan_id="plan-1",
            task_id="task-1",
            step_id="step-1",
            capability_id="phase5.capability",
            operation_id="phase5.run",
        )
        for version in ("elly.step-result.v0", "elly.step-result.unknown"):
            payload = envelope.to_dict()
            payload["schema_version"] = version
            with self.assertRaises(MalformedResultError):
                StepResultEnvelope.from_dict(payload)
        malformed = envelope.to_dict()
        malformed.pop("task_id")
        with self.assertRaises(MalformedResultError):
            StepResultEnvelope.from_dict(malformed)

    def test_absent_and_contradicted_evidence_are_distinct(self) -> None:
        envelope = StepResultEnvelope(
            schema_version="elly.step-result.v1",
            plan_id="plan-1",
            task_id="task-1",
            step_id="step-1",
            capability_id="phase5.capability",
            operation_id="phase5.run",
            status=TaskStatus.COMPLETED,
            summary="qualified findings",
            answer="qualified findings",
            claims=(
                StepClaim(
                    "claim-1", "evidence is absent", support_status=EvidenceStatus.ABSENT.value
                ),
                StepClaim(
                    "claim-2",
                    "evidence contradicts this",
                    evidence_ids=("e-1",),
                    support_status=EvidenceStatus.CONTRADICTED.value,
                ),
            ),
            claim_supports=(
                ClaimSupport("claim-1", "evidence is absent", "absent"),
                ClaimSupport("claim-2", "evidence contradicts this", "contradicted", ("e-1",)),
            ),
            usage=StepUsage(output_tokens=4, latency_ms=12),
        )
        restored = StepResultEnvelope.from_dict(envelope.to_dict())
        self.assertEqual(
            ("absent", "contradicted"),
            tuple(item.support_status for item in restored.claim_supports),
        )


class AuthorizationBindingTests(unittest.TestCase):
    def test_consent_is_bound_to_plan_step_provider_purpose_payload_and_expiry(self) -> None:
        consent = ConsentWorkflow(ttl_seconds=30)
        policy = CloudAuthorizationPolicy()
        request = CloudAuthorizationRequest(
            task_id="task-1",
            plan_id="plan-1",
            step_id="step-1",
            operation="phase5.run",
            payload="my private record",
            classification=PrivacyPolicy().classify("my private record"),
            cloud_mode=CloudMode.CLOUD_PERMITTED,
            destination="provider-a",
            model="model-a",
            capability_id="phase5.capability",
            purpose="phase five test",
            consent=consent,
            approval_id=None,
            max_cost=0.25,
            now=UTC,
        )
        first = policy.authorize(request)
        self.assertFalse(first.allowed)
        assert first.consent_proposal is not None
        consent.approve(first.consent_proposal.proposal_id, now=UTC)
        self.assertFalse(
            policy.authorize(
                replace(
                    request,
                    destination="provider-b",
                    approval_id=first.consent_proposal.proposal_id,
                )
            ).allowed
        )
        self.assertFalse(
            policy.authorize(
                replace(request, step_id="step-2", approval_id=first.consent_proposal.proposal_id)
            ).allowed
        )
        self.assertTrue(
            policy.authorize(
                replace(request, approval_id=first.consent_proposal.proposal_id)
            ).allowed
        )

        expired = policy.authorize(replace(request, approval_id=None, now=UTC))
        assert expired.consent_proposal is not None
        consent.approve(expired.consent_proposal.proposal_id, now=UTC)
        self.assertFalse(
            policy.authorize(
                replace(
                    request,
                    approval_id=expired.consent_proposal.proposal_id,
                    now=UTC + timedelta(seconds=31),
                )
            ).allowed
        )

    def test_derived_result_is_reclassified_before_external_boundary(self) -> None:
        derived = "objective: summarize\nsource: my private record"
        classification = PrivacyPolicy().classify(derived)
        self.assertEqual("local", classification.classification.value)
        decision = CloudAuthorizationPolicy().authorize(
            CloudAuthorizationRequest(
                task_id="task-1",
                plan_id="plan-1",
                step_id="step-2",
                operation="phase5.run",
                payload=derived,
                classification=classification,
                cloud_mode=CloudMode.CLOUD_PERMITTED,
                destination="provider-a",
                model="model-a",
                capability_id="phase5.capability",
                purpose="phase five derived summary",
                consent=ConsentWorkflow(),
                approval_id=None,
                max_cost=0.25,
                now=UTC,
            )
        )
        self.assertFalse(decision.allowed)
        self.assertEqual("EXACT_CONSENT_REQUIRED", decision.reason_code)

    def test_action_completion_without_verified_receipt_is_not_successful(self) -> None:
        action = ActionProposal(
            category=ActionCategory.EXTERNAL_COMMUNICATION,
            target=ActionTarget("email", "owner@example.invalid"),
            side_effect=ActionSideEffect.EXTERNAL_STATE,
            reversibility=ActionReversibility.REVERSIBLE,
            data_sensitivity=ActionDataSensitivity.PUBLIC,
            impact_flags=(ActionImpactFlag.COMMUNICATION,),
            confirmation_required=True,
            source=ActionProposalSource.CAPABILITY_DECLARED,
        )
        capability = _Capability(action=action, receipt=False)
        plan = _plan_for("phase5.capability", "phase5.run", effect=action.category)
        workflow = _workflow(capability)
        request = _request("phase5-action")
        first = workflow.execute_plan_step(
            plan=plan,
            step=plan.steps[0],
            request=request,
            context_text="public action request",
            context_manifest=ContextManifest((), {}, 32, 2),
            cancellation=CancellationToken(),
        )
        self.assertIsNotNone(first.action_confirmation)
        assert first.action_confirmation is not None
        workflow._action_authorization.confirmations.approve(
            first.action_confirmation.confirmation_id, now=UTC
        )
        approved = _request(
            "phase5-action", action_confirmation_id=first.action_confirmation.confirmation_id
        )
        second = workflow.execute_plan_step(
            plan=plan,
            step=plan.steps[0],
            request=approved,
            context_text="public action request",
            context_manifest=ContextManifest((), {}, 32, 2),
            cancellation=CancellationToken(),
        )
        self.assertEqual(TaskStatus.FAILED, second.result.task_status)
        self.assertEqual(1, capability.calls)

    def test_provider_exception_is_normalized_at_capability_boundary(self) -> None:
        capability = _Capability(raises=True)
        workflow = _workflow(capability)
        plan = _plan_for("phase5.capability", "phase5.run")
        result = workflow.execute_plan_step(
            plan=plan,
            step=plan.steps[0],
            request=_request("phase5-provider"),
            context_text="public request",
            context_manifest=ContextManifest((), {}, 32, 2),
            cancellation=CancellationToken(),
        )
        self.assertEqual(TaskStatus.FAILED, result.result.task_status)
        self.assertEqual(("capability provider failed",), result.result.failures)

    def test_verified_action_receipt_allows_typed_completion(self) -> None:
        action = ActionProposal(
            category=ActionCategory.EXTERNAL_COMMUNICATION,
            target=ActionTarget("email", "owner@example.invalid"),
            side_effect=ActionSideEffect.EXTERNAL_STATE,
            reversibility=ActionReversibility.REVERSIBLE,
            data_sensitivity=ActionDataSensitivity.PUBLIC,
            impact_flags=(ActionImpactFlag.COMMUNICATION,),
            confirmation_required=True,
            source=ActionProposalSource.CAPABILITY_DECLARED,
        )
        capability = _Capability(action=action, receipt=True)
        plan = _plan_for("phase5.capability", "phase5.run", effect=action.category)
        workflow = _workflow(capability)
        first = workflow.execute_plan_step(
            plan=plan,
            step=plan.steps[0],
            request=_request("phase5-receipt"),
            context_text="public action request",
            context_manifest=ContextManifest((), {}, 32, 2),
            cancellation=CancellationToken(),
        )
        assert first.action_confirmation is not None
        workflow._action_authorization.confirmations.approve(
            first.action_confirmation.confirmation_id, now=UTC
        )
        second = workflow.execute_plan_step(
            plan=plan,
            step=plan.steps[0],
            request=_request(
                "phase5-receipt",
                action_confirmation_id=first.action_confirmation.confirmation_id,
            ),
            context_text="public action request",
            context_manifest=ContextManifest((), {}, 32, 2),
            cancellation=CancellationToken(),
        )
        self.assertEqual(TaskStatus.COMPLETED, second.result.task_status)
        self.assertIsNotNone(second.result_envelope)


class EnvelopePersistenceTests(unittest.TestCase):
    def test_versioned_envelope_is_persisted_and_legacy_result_view_remains_available(self) -> None:
        repository = SqliteSessionRepository(":memory:")
        self.addCleanup(repository.close)
        repository.apply_migrations()
        plan = _plan_for("phase5.capability", "phase5.run")
        repository.save_plan(plan, at=UTC)
        envelope = normalize_step_result(
            _legacy_result(plan.task_id, "persisted"),
            plan_id=plan.plan_id,
            task_id=plan.task_id,
            step_id=plan.steps[0].step_id,
            capability_id=plan.steps[0].capability_id,
            operation_id=plan.steps[0].operation_id,
        )
        repository.save_step_envelope(plan.plan_id, plan.steps[0].step_id, envelope, at=UTC)
        self.assertEqual(
            envelope, repository.get_step_envelope(plan.plan_id, plan.steps[0].step_id)
        )
        self.assertEqual(
            "persisted", repository.get_step_result(plan.plan_id, plan.steps[0].step_id).answer
        )  # type: ignore[union-attr]

    def test_task_execution_returns_and_persists_typed_envelope(self) -> None:
        repository = SqliteSessionRepository(":memory:")
        self.addCleanup(repository.close)
        repository.apply_migrations()
        clock = FixedClock(UTC)
        repository.create_session(
            SessionRecord(
                "phase5-session",
                PersistenceMode.STORE_WITH_RETENTION,
                CloudMode.LOCAL_ONLY,
                UTC,
            )
        )
        capability = _Capability()
        registry = CapabilityRegistry((capability,))
        plan = _plan_for("phase5.capability", "phase5.run")
        repository.save_plan(plan, at=UTC)
        repository.start_task(plan.task_id, "phase5-session", UTC)
        workflow = CapabilityExecutionWorkflow(
            clock=clock,
            capability_registry=registry,
            completion=CompletionService(
                clock=clock, repository=repository, audit=StructuredAuditLog()
            ),
        )
        execution = TaskExecutionService(
            repository=repository,
            capability_registry=registry,
            capability_workflow=workflow,
            clock=clock,
        ).execute(
            plan,
            PlanExecutionRequest(
                request=_request("phase5-plan"),
                context_text="public request",
                context_manifest=ContextManifest((), {}, 32, 2),
            ),
        )
        self.assertEqual(TaskStatus.COMPLETED, execution.step_results["step-one"].task_status)
        self.assertIsNotNone(execution.envelopes["step-one"])
        self.assertEqual(
            execution.envelopes["step-one"],
            repository.get_step_envelope(plan.plan_id, "step-one"),
        )


def _request(request_id: str, *, action_confirmation_id: str | None = None) -> TaskRequest:
    return TaskRequest(
        request_id=request_id,
        session_id="phase5-session",
        text="phase five request",
        cloud_mode=CloudMode.LOCAL_ONLY,
        persistence_mode=PersistenceMode.STORE_WITH_RETENTION,
        submitted_at=UTC,
        action_confirmation_id=action_confirmation_id,
    )


def _workflow(capability: _Capability) -> CapabilityExecutionWorkflow:
    repository = SqliteSessionRepository(":memory:")
    repository.apply_migrations()
    # The repository is intentionally owned by the workflow for this small
    # direct-boundary test; no task completion is persisted on the plan path.
    completion = CompletionService(
        clock=FixedClock(UTC), repository=repository, audit=StructuredAuditLog()
    )
    workflow = CapabilityExecutionWorkflow(
        clock=FixedClock(UTC),
        capability_registry=CapabilityRegistry((capability,)),
        completion=completion,
        consent=ConsentWorkflow(),
    )
    # Keep the in-memory database alive for the lifetime of the test workflow.
    workflow._phase5_test_repository = repository  # type: ignore[attr-defined]
    return workflow


if __name__ == "__main__":
    unittest.main()

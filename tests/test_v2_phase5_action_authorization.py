"""Phase 5 typed consequential-action authorization contracts."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from elly.adapters.audit_log import StructuredAuditLog
from elly.adapters.fake_generalist import FakeGeneralist
from elly.adapters.openai_specialist import OpenAISpecialistProvider
from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.adapters.system_clock import FixedClock
from elly.api.application import EllyApplication
from elly.api.contracts import (
    ActionDecisionRequest,
    CapabilityIntentInput,
    CreateSessionRequest,
    SubmitRequest,
)
from elly.application.action_authorization import (
    ActionAuthorizationPolicy,
    ActionAuthorizationRequest,
    ActionAuthorizationService,
    interpret_recommended_action,
)
from elly.application.capabilities import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityExecution,
    CapabilityMatch,
    CapabilityPreparation,
    CapabilityRegistry,
    CapabilityRequest,
    CapabilityStatus,
)
from elly.application.capability_workflow import (
    CapabilityExecutionCommand,
    CapabilityExecutionWorkflow,
)
from elly.application.completion import CompletionService
from elly.application.execution import CancellationToken
from elly.application.specialist_policy import SpecialistPolicyRequest
from elly.application.specialists import SpecialistWorkflow
from elly.composition import Application
from elly.config import load_config
from elly.domain.enums import (
    ActionCategory,
    ActionDataSensitivity,
    ActionImpactFlag,
    ActionProposalSource,
    ActionReversibility,
    ActionSideEffect,
    CloudMode,
    EpistemicStatus,
    IntentAmbiguity,
    PersistenceMode,
    Route,
    RouteReasonCode,
    TaskStatus,
    ValidationStatus,
)
from elly.domain.models import (
    ActionProposal,
    ActionTarget,
    CapabilityIntent,
    ContextManifest,
    RouteDecision,
    RouteRequest,
    SessionRecord,
    TaskRequest,
    TaskResult,
)
from elly.privacy import ConsentWorkflow, classify_payload
from elly.specialists.contracts import SpecialistResult, SpecialistTask
from elly.specialists.fake_provider import FakeSpecialistProvider
from elly.specialists.manifest import SpecialistManifest

UTC = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


def _communication() -> ActionProposal:
    return ActionProposal(
        category=ActionCategory.EXTERNAL_COMMUNICATION,
        target=ActionTarget("recipient", "John"),
        side_effect=ActionSideEffect.EXTERNAL_STATE,
        reversibility=ActionReversibility.PARTIALLY_REVERSIBLE,
        data_sensitivity=ActionDataSensitivity.LOCAL,
        impact_flags=(ActionImpactFlag.COMMUNICATION,),
        source=ActionProposalSource.MODEL_PROPOSED,
    )


def _specialist_request() -> SpecialistPolicyRequest:
    manifest = SpecialistManifest(
        id="coding",
        version="1.0",
        description="coding",
        role="coding",
        capabilities=frozenset({"review"}),
        accepted_inputs=frozenset({"text"}),
        requires_current_data=False,
        preferred_runtime="cloud",
        risk_level="low",
        estimated_cost="medium",
        timeout_seconds=30,
    )
    task = SpecialistTask(
        task_id="task-action",
        specialist_id="coding",
        goal="review",
        context="Review this public function",
        privacy_class=classify_payload("Review this public function").value,
    )
    return SpecialistPolicyRequest(task=task, manifest=manifest)


class ActionPolicyTests(unittest.TestCase):
    def test_draft_is_not_external_write_even_with_write_word(self) -> None:
        proposal = interpret_recommended_action("Write cleaner documentation")
        assert proposal is not None
        self.assertEqual(ActionCategory.CONTENT_DRAFT, proposal.category)
        decision = ActionAuthorizationPolicy().evaluate(proposal)
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.confirmation_required)

    def test_transmit_is_communication_and_requires_exact_confirmation(self) -> None:
        proposal = interpret_recommended_action("Transmit this message to John")
        assert proposal is not None
        self.assertEqual(ActionCategory.EXTERNAL_COMMUNICATION, proposal.category)
        self.assertEqual("John", proposal.target.reference if proposal.target else None)
        service = ActionAuthorizationService()
        request = ActionAuthorizationRequest(
            task_id="task-1",
            capability_id="messaging",
            operation="message.send",
            proposal=proposal,
            now=UTC,
        )
        pending = service.authorize(request)
        self.assertFalse(pending.allowed)
        self.assertEqual("ACTION_CONFIRMATION_REQUIRED", pending.reason_code)
        assert pending.confirmation_proposal is not None
        service.confirmations.approve(pending.confirmation_proposal.confirmation_id, now=UTC)
        approved = service.authorize(
            ActionAuthorizationRequest(
                task_id="task-1",
                capability_id="messaging",
                operation="message.send",
                proposal=proposal,
                confirmation_id=pending.confirmation_proposal.confirmation_id,
                now=UTC,
            )
        )
        self.assertTrue(approved.allowed)
        replay = service.authorize(
            ActionAuthorizationRequest(
                task_id="task-1",
                capability_id="messaging",
                operation="message.send",
                proposal=proposal,
                confirmation_id=pending.confirmation_proposal.confirmation_id,
                now=UTC,
            )
        )
        self.assertFalse(replay.allowed)
        self.assertEqual("ACTION_CONFIRMATION_INVALID", replay.reason_code)

    def test_confirmation_is_bound_to_target_operation_and_digest(self) -> None:
        service = ActionAuthorizationService()
        proposal = _communication()
        first = service.authorize(
            ActionAuthorizationRequest("task-1", "messaging", "message.send", proposal, now=UTC)
        )
        assert first.confirmation_proposal is not None
        confirmation_id = first.confirmation_proposal.confirmation_id
        service.confirmations.approve(confirmation_id, now=UTC)
        changed_target = ActionProposal(
            category=proposal.category,
            target=ActionTarget("recipient", "Mary"),
            side_effect=proposal.side_effect,
            reversibility=proposal.reversibility,
            data_sensitivity=proposal.data_sensitivity,
            impact_flags=proposal.impact_flags,
            confirmation_required=proposal.confirmation_required,
            source=proposal.source,
        )
        denied = service.authorize(
            ActionAuthorizationRequest(
                "task-1",
                "messaging",
                "message.send",
                changed_target,
                confirmation_id=confirmation_id,
                now=UTC,
            )
        )
        self.assertFalse(denied.allowed)
        self.assertEqual("ACTION_CONFIRMATION_INVALID", denied.reason_code)

    def test_required_categories_fail_closed_when_typed_fields_are_ambiguous(self) -> None:
        policy = ActionAuthorizationPolicy()
        cases = (
            ActionProposal(
                category=ActionCategory.DELETE,
                side_effect=ActionSideEffect.LOCAL_STATE,
                reversibility=ActionReversibility.IRREVERSIBLE,
                data_sensitivity=ActionDataSensitivity.LOCAL,
                impact_flags=(ActionImpactFlag.DELETION,),
            ),
            ActionProposal(
                category=ActionCategory.EXTERNAL_COMMUNICATION,
                target=ActionTarget("recipient", "John"),
                side_effect=ActionSideEffect.EXTERNAL_STATE,
                reversibility=ActionReversibility.UNKNOWN,
                data_sensitivity=ActionDataSensitivity.LOCAL,
                impact_flags=(ActionImpactFlag.COMMUNICATION,),
            ),
            ActionProposal(
                category=ActionCategory.FINANCIAL_TRANSACTION,
                target=ActionTarget("account", "checking"),
                side_effect=ActionSideEffect.EXTERNAL_STATE,
                reversibility=ActionReversibility.PARTIALLY_REVERSIBLE,
                data_sensitivity=ActionDataSensitivity.UNCLASSIFIED,
                impact_flags=(ActionImpactFlag.FINANCIAL,),
            ),
        )
        for proposal in cases:
            with self.subTest(category=proposal.category):
                decision = policy.evaluate(proposal)
                self.assertFalse(decision.allowed)

    def test_capability_minimum_risk_cannot_be_lowered_by_model(self) -> None:
        declared = ActionProposal(
            category=ActionCategory.EXTERNAL_COMMUNICATION,
            target=ActionTarget("recipient", "John"),
            side_effect=ActionSideEffect.EXTERNAL_STATE,
            reversibility=ActionReversibility.PARTIALLY_REVERSIBLE,
            data_sensitivity=ActionDataSensitivity.LOCAL,
            impact_flags=(ActionImpactFlag.COMMUNICATION,),
            confirmation_required=True,
        )
        lower = ActionProposal.none(source=ActionProposalSource.MODEL_PROPOSED)
        decision = ActionAuthorizationPolicy().evaluate(lower, declared_action=declared)
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.confirmation_required)
        self.assertEqual(ActionCategory.EXTERNAL_COMMUNICATION, decision.proposal.category)


class _EffectfulCapability:
    descriptor = CapabilityDescriptor(
        capability_id="phase5.messaging",
        description="Phase 5 confirmation test capability",
        routes=(Route.CODING_SPECIALIST,),
        request_schema="phase5-message-v1",
        operations=("message.send",),
        declared_action=_communication(),
        requires_external_boundary=False,
    )

    def __init__(self) -> None:
        self.calls = 0

    def status(self) -> CapabilityStatus:
        return CapabilityStatus(CapabilityAvailability.AVAILABLE)

    def can_handle(self, _request: CapabilityRequest) -> CapabilityMatch:
        return CapabilityMatch(True, "TEST_MATCH")

    def prepare(self, _intent, _request: CapabilityRequest) -> CapabilityPreparation:
        return CapabilityPreparation(True, "TEST_PREPARED")

    def propose_action(self, _request: CapabilityRequest) -> ActionProposal:
        return self.descriptor.declared_action

    def execute(self, request: CapabilityRequest) -> CapabilityExecution:
        self.calls += 1
        return CapabilityExecution(
            TaskResult(
                task_id=request.task_id,
                task_status=TaskStatus.COMPLETED,
                epistemic_status=EpistemicStatus.INFERRED,
                validation_status=ValidationStatus.VALIDATED,
                answer="message sent",
                route_summary=Route.CODING_SPECIALIST,
            ),
            request.context_manifest,
        )


class CapabilityConfirmationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = SqliteSessionRepository(":memory:")
        self.repository.apply_migrations()
        self.repository.create_session(
            SessionRecord(
                "phase5-session",
                PersistenceMode.STORE_WITH_RETENTION,
                CloudMode.LOCAL_ONLY,
                UTC,
            )
        )
        self.clock = FixedClock(UTC)
        self.audit = StructuredAuditLog()
        self.completion = CompletionService(
            clock=self.clock, repository=self.repository, audit=self.audit
        )
        self.capability = _EffectfulCapability()
        self.action_authorization = ActionAuthorizationService()
        self.workflow = CapabilityExecutionWorkflow(
            clock=self.clock,
            capability_registry=CapabilityRegistry((self.capability,)),
            completion=self.completion,
            action_authorization=self.action_authorization,
        )
        self.addCleanup(self.repository.close)

    def _command(self, request: TaskRequest) -> CapabilityExecutionCommand:
        task_id = f"task-{request.request_id}"
        self.repository.start_task(task_id, request.session_id, UTC)
        intent = CapabilityIntent(
            proposed_capability_id="phase5.messaging",
            operation="message.send",
            arguments={"subject": "message"},
            confidence=1.0,
            ambiguity=IntentAmbiguity.CLEAR,
            rationale_code="TEST",
        )
        return CapabilityExecutionCommand(
            request=request,
            task_id=task_id,
            status=TaskStatus.RUNNING,
            route=Route.CODING_SPECIALIST,
            route_request=RouteRequest(
                request_id=request.request_id,
                text=request.text,
                cloud_mode=request.cloud_mode,
            ),
            route_decision=RouteDecision(
                route=Route.CODING_SPECIALIST,
                reason_code=RouteReasonCode.PROPOSAL_ACCEPTED,
                capability_id="phase5.messaging",
                operation="message.send",
                intent=intent,
            ),
            context_text=request.text,
            context_manifest=ContextManifest((), {}, 32, 2),
            cancellation=CancellationToken(),
        )

    def test_effectful_capability_waits_before_provider_and_runs_after_exact_approval(self) -> None:
        request = TaskRequest(
            request_id="phase5-send",
            session_id="phase5-session",
            text="message body",
            cloud_mode=CloudMode.LOCAL_ONLY,
            persistence_mode=PersistenceMode.STORE_WITH_RETENTION,
            submitted_at=UTC,
        )
        first = self.workflow.execute(self._command(request))
        self.assertEqual(TaskStatus.AWAITING_CONFIRMATION, first.result.task_status)
        self.assertEqual(0, self.capability.calls)
        assert first.action_confirmation is not None
        self.action_authorization.confirmations.approve(
            first.action_confirmation.confirmation_id, now=UTC
        )
        approved = TaskRequest(
            request_id=request.request_id,
            session_id=request.session_id,
            text=request.text,
            cloud_mode=request.cloud_mode,
            persistence_mode=request.persistence_mode,
            submitted_at=request.submitted_at,
            action_confirmation_id=first.action_confirmation.confirmation_id,
        )
        second = self.workflow.execute(self._command(approved))
        self.assertEqual(TaskStatus.COMPLETED, second.result.task_status)
        self.assertEqual(1, self.capability.calls)


class PublicActionConfirmationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = SqliteSessionRepository(":memory:")
        self.repository.apply_migrations()
        self.clock = FixedClock(UTC)
        self.audit = StructuredAuditLog()
        self.capability = _EffectfulCapability()
        self.application = Application(
            config=load_config(None),
            clock=self.clock,
            generalist=FakeGeneralist(model_id="test-generalist"),
            repository=self.repository,
            audit=self.audit,
            capability_registry=CapabilityRegistry((self.capability,)),
            consent=ConsentWorkflow(),
        )
        self.api = EllyApplication(self.application)

    def tearDown(self) -> None:
        self.api.close()

    def test_public_api_exposes_and_consumes_exact_action_confirmation(self) -> None:
        session = self.api.create_session(CreateSessionRequest())
        assert session.value is not None
        intent = CapabilityIntentInput(
            proposed_capability_id="phase5.messaging",
            operation="message.send",
            arguments=(("subject", "message"),),
            confidence=1.0,
            ambiguity=IntentAmbiguity.CLEAR.value,
            rationale_code="TEST",
        )
        pending = self.api.submit_and_wait(
            SubmitRequest(
                "api-action-1",
                session.value.session_id,
                "message body",
                capability_intent=intent,
            )
        )
        self.assertTrue(pending.is_success)
        assert pending.value is not None
        self.assertEqual(TaskStatus.AWAITING_CONFIRMATION, pending.value.status)
        assert pending.value.action_confirmation is not None
        confirmation_id = pending.value.action_confirmation.confirmation_id
        approved = self.api.decide_action(ActionDecisionRequest(confirmation_id, True))
        self.assertTrue(approved.is_success)
        assert approved.value is not None
        self.assertEqual(TaskStatus.COMPLETED, approved.value.status)
        self.assertEqual(1, self.capability.calls)

    def test_public_api_action_denial_persists_once_and_never_dispatches(self) -> None:
        session = self.api.create_session(CreateSessionRequest())
        assert session.value is not None
        intent = CapabilityIntentInput(
            proposed_capability_id="phase5.messaging",
            operation="message.send",
            arguments=(("subject", "message"),),
            confidence=1.0,
            ambiguity=IntentAmbiguity.CLEAR.value,
            rationale_code="TEST",
        )
        pending = self.api.submit_and_wait(
            SubmitRequest(
                "api-action-denied",
                session.value.session_id,
                "message body",
                capability_intent=intent,
            )
        )
        self.assertTrue(pending.is_success)
        assert pending.value is not None
        self.assertEqual(TaskStatus.AWAITING_CONFIRMATION, pending.value.status)
        assert pending.value.action_confirmation is not None
        confirmation_id = pending.value.action_confirmation.confirmation_id

        repository = self.application.repository
        with patch.object(repository, "save_task_result", wraps=repository.save_task_result) as save:
            denied = self.api.decide_action(ActionDecisionRequest(confirmation_id, False))

        self.assertTrue(denied.is_success, denied.failure)
        assert denied.value is not None
        self.assertEqual(TaskStatus.BLOCKED, denied.value.status)
        self.assertEqual(0, self.capability.calls)
        self.assertEqual(1, save.call_count)
        self.assertIsNone(self.application.runtime.authorization_task_id(confirmation_id))
        replay = self.api.decide_action(ActionDecisionRequest(confirmation_id, False))
        self.assertFalse(replay.is_success)
        assert replay.failure is not None
        self.assertEqual("NOT_FOUND", replay.failure.code.value)


class SpecialistActionTests(unittest.TestCase):
    def test_specialist_draft_is_allowed_and_transmit_is_typed_not_keyword_blocked(self) -> None:
        draft_provider = FakeSpecialistProvider(
            result=SpecialistResult(
                status="known", answer="answer", recommended_action="Write cleaner documentation"
            )
        )
        draft = SpecialistWorkflow(provider=draft_provider).execute(request=_specialist_request())
        self.assertEqual(ActionCategory.CONTENT_DRAFT, draft.action_proposal.category)

        transmit_provider = FakeSpecialistProvider(
            result=SpecialistResult(
                status="known", answer="answer", recommended_action="Transmit this message to John"
            )
        )
        transmit = SpecialistWorkflow(provider=transmit_provider).execute(
            request=_specialist_request()
        )
        assert transmit.action_proposal is not None
        self.assertEqual(ActionCategory.EXTERNAL_COMMUNICATION, transmit.action_proposal.category)

    def test_ambiguous_irreversible_recommendation_fails_closed(self) -> None:
        provider = FakeSpecialistProvider(
            result=SpecialistResult(
                status="known", answer="answer", recommended_action="execute this command"
            )
        )
        with self.assertRaises(Exception):
            SpecialistWorkflow(provider=provider).execute(request=_specialist_request())
        self.assertEqual(1, len(provider.calls))


class _Response:
    def __init__(self, value: dict) -> None:
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.value).encode()


class StructuredProviderActionTests(unittest.TestCase):
    def test_typed_model_action_proposal_is_schema_parsed(self) -> None:
        body = {
            "output_text": json.dumps(
                {
                    "status": "known",
                    "answer": "answer",
                    "assumptions": [],
                    "uncertainties": [],
                    "key_evidence": [],
                    "sources": [],
                    "recommended_action": None,
                    "action_proposal": {
                        "category": "external_communication",
                        "target": {"kind": "recipient", "reference": "John"},
                        "side_effect": "external_state",
                        "reversibility": "partially_reversible",
                        "data_sensitivity": "local",
                        "impact_flags": ["communication"],
                        "confirmation_required": False,
                        "source": "model_proposed",
                    },
                }
            )
        }
        provider = OpenAISpecialistProvider(api_key="test-key")
        with patch(
            "elly.adapters.openai_specialist.urllib.request.urlopen",
            return_value=_Response(body),
        ):
            result = provider.execute(
                _specialist_request().task,
                model="gpt-test",
                prompt_version="v1",
                output_limit=100,
            )
        assert result.action_proposal is not None
        self.assertEqual(
            ActionCategory.EXTERNAL_COMMUNICATION,
            result.action_proposal.category,
        )


if __name__ == "__main__":
    unittest.main()

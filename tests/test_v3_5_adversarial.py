"""Independent hostile-output and fallback regressions for Elly V3.5."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone

from elly.adapters.fake_response_composer import FakeResponseComposer
from elly.application.plan_results import aggregate_plan_results
from elly.application.response_composer import compose_success
from elly.application.response_pipeline import ResponseCompositionService
from elly.application.step_results import ActionExecutionReceipt, StepResultEnvelope
from elly.domain.enums import CloudMode, PersistenceMode, PresentationMode, TaskStatus
from elly.domain.models import TaskRequest
from elly.planning.contracts import StepState
from elly.ports.local_response_composer import (
    RESPONSE_COMPOSITION_DRAFT_SCHEMA_VERSION,
    ResponseCompositionDraft,
    ResponseSection,
)
from tests.test_execution_aggregation import _envelope, _plan, _step

UTC = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


def _request() -> TaskRequest:
    return TaskRequest(
        request_id="request-v35-hostile",
        session_id="session-v35-hostile",
        text="What is the amount and did the action execute?",
        cloud_mode=CloudMode.LOCAL_ONLY,
        persistence_mode=PersistenceMode.STORE_WITH_RETENTION,
        submitted_at=UTC,
    )


class _Composer:
    def __init__(self, behavior: object) -> None:
        self.behavior = behavior
        self.calls = 0

    def compose(self, request: object) -> object:
        self.calls += 1
        if isinstance(self.behavior, BaseException):
            raise self.behavior
        return self.behavior(request)  # type: ignore[operator]

    def cancel(self) -> None:
        return None


class V35AdversarialTests(unittest.TestCase):
    def test_model_authored_facts_authorization_and_status_prose_are_rejected(self) -> None:
        def hostile(request: object) -> ResponseCompositionDraft:
            value = request.composition_input  # type: ignore[attr-defined]
            return ResponseCompositionDraft(
                schema_version=RESPONSE_COMPOSITION_DRAFT_SCHEMA_VERSION,
                sections=(
                    ResponseSection(
                        section_id="hostile",
                        title="Action completed successfully for $125 on 2099-01-01",
                        narrative="Authorization was granted and the blocked task succeeded.",
                        result_refs=value.result_refs,
                        claim_refs=value.claim_refs,
                        citation_refs=value.citation_refs,
                        immutable_record_refs=value.immutable_record_refs,
                    ),
                ),
                referenced_result_ids=value.result_refs,
                referenced_claim_ids=value.claim_refs,
                referenced_citation_ids=value.citation_refs,
                acknowledged_warning_ids=value.warning_refs,
                acknowledged_disagreement_ids=value.disagreement_refs,
                referenced_immutable_record_ids=value.immutable_record_refs,
                task_status=value.task_status,
            )

        composer = _Composer(hostile)
        canonical = replace(
            compose_success(
                task_id="task-v35-hostile",
                answer="Canonical amount: $12.50; action_executed=false",
            ),
            failures=("canonical limitation",),
        )
        output = ResponseCompositionService(composer=composer).compose_task_result(
            canonical, request=_request()
        )

        self.assertEqual(1, composer.calls)
        self.assertEqual("rejected", output.observation.outcome)
        self.assertIn("$12.50", output.result.answer)
        self.assertNotIn("$125", output.result.answer)
        self.assertNotIn("Authorization was granted", output.result.answer)
        self.assertEqual(canonical.task_status, output.result.task_status)
        self.assertEqual(canonical.failures, output.result.failures)

    def test_omitting_approved_claim_and_citation_rejects_the_draft(self) -> None:
        def omit(request: object) -> ResponseCompositionDraft:
            value = request.composition_input  # type: ignore[attr-defined]
            return ResponseCompositionDraft(
                schema_version=RESPONSE_COMPOSITION_DRAFT_SCHEMA_VERSION,
                sections=(ResponseSection("omit", result_refs=value.result_refs),),
                referenced_result_ids=value.result_refs,
                task_status=value.task_status,
            )

        composer = _Composer(omit)
        canonical = replace(
            compose_success(task_id="task-v35-omit", answer="canonical answer"),
            claims=("canonical amount is $12.50",),
            citations=("https://canonical.example/evidence",),
        )
        output = ResponseCompositionService(composer=composer).compose_task_result(
            canonical, request=_request()
        )

        self.assertEqual("rejected", output.observation.outcome)
        self.assertIn("canonical amount is $12.50", output.result.answer)
        self.assertIn("https://canonical.example/evidence", output.result.answer)

    def test_plan_action_receipt_is_byte_exact_once(self) -> None:
        step = _step("action")
        plan = _plan(step)
        receipt = ActionExecutionReceipt(
            receipt_id="receipt-v35",
            action_digest="a" * 64,
            capability_id=step.capability_id,
            operation_id=step.operation_id,
            completed_at=UTC,
        )
        exact = (
            f"{receipt.receipt_id}: succeeded; capability={receipt.capability_id}; "
            f"operation={receipt.operation_id}; digest={receipt.action_digest}"
        )
        envelope = StepResultEnvelope(
            schema_version="elly.step-result.v1",
            plan_id=plan.plan_id,
            task_id=plan.task_id,
            step_id=step.step_id,
            capability_id=step.capability_id,
            operation_id=step.operation_id,
            status=TaskStatus.COMPLETED,
            summary="action completed",
            answer="action completed",
            action_receipt=receipt,
        )
        aggregation = aggregate_plan_results(
            plan,
            step_envelopes={step.step_id: envelope},
            states={step.step_id: StepState.COMPLETED},
        )
        composer = FakeResponseComposer()
        output = ResponseCompositionService(composer=composer).compose_aggregation(
            aggregation, request=_request()
        )

        self.assertEqual(PresentationMode.EXACT_WITH_COMPOSED_CONTEXT, output.mode)
        self.assertEqual(1, len(composer.requests))
        self.assertEqual("accepted", output.observation.outcome)
        self.assertIn(exact, output.result.answer)
        self.assertEqual(1, output.result.answer.count(exact))

    def test_major_invalid_outputs_fall_back_once_without_state_changes(self) -> None:
        canonical = replace(
            compose_success(task_id="task-v35-fallback", answer="canonical $12.50"),
            claims=("canonical claim",),
            citations=("https://canonical.example/source",),
        )

        def wrong_schema(_request: object) -> str:
            return (
                '{"schema_version":"wrong","sections":[],"referenced_result_ids":[],'
                '"referenced_claim_ids":[],"referenced_citation_ids":[],'
                '"acknowledged_warning_ids":[],"acknowledged_disagreement_ids":[],'
                '"referenced_immutable_record_ids":[]}'
            )

        def cross_task(request: object) -> ResponseCompositionDraft:
            value = request.composition_input  # type: ignore[attr-defined]
            return ResponseCompositionDraft(
                schema_version=RESPONSE_COMPOSITION_DRAFT_SCHEMA_VERSION,
                sections=(ResponseSection("unknown", result_refs=("result-other-task",)),),
                referenced_result_ids=("result-other-task",),
                task_status=value.task_status,
            )

        cases = {
            "unavailable": RuntimeError("provider unavailable"),
            "timeout": TimeoutError("timed out"),
            "malformed_json": lambda _request: "not-json",
            "schema_mismatch": wrong_schema,
            "cross_task": cross_task,
        }
        for name, behavior in cases.items():
            with self.subTest(name=name):
                composer = _Composer(behavior)
                output = ResponseCompositionService(composer=composer).compose_task_result(
                    canonical, request=_request()
                )
                self.assertEqual(1, composer.calls)
                self.assertEqual("rejected", output.observation.outcome)
                self.assertEqual(canonical.task_status, output.result.task_status)
                self.assertEqual(canonical.failures, output.result.failures)
                self.assertIn("canonical $12.50", output.result.answer)
                self.assertIn("canonical claim", output.result.answer)
                self.assertIn("https://canonical.example/source", output.result.answer)

    def test_warning_and_disagreement_omission_falls_back_with_both_visible(self) -> None:
        left = _step("left")
        right = _step("right")
        plan = _plan(left, right)
        left_envelope = replace(
            _envelope(plan, left, "alpha"), warnings=("mandatory warning",)
        )
        aggregation = aggregate_plan_results(
            plan,
            step_envelopes={
                "left": left_envelope,
                "right": _envelope(plan, right, "beta"),
            },
            states={"left": StepState.COMPLETED, "right": StepState.COMPLETED},
        )

        def omit_acknowledgements(request: object) -> ResponseCompositionDraft:
            value = request.composition_input  # type: ignore[attr-defined]
            sections = tuple(
                ResponseSection(
                    section_id=f"section-{index}",
                    result_refs=(summary.result_ref,),
                    claim_refs=summary.claim_refs,
                    citation_refs=summary.citation_refs,
                )
                for index, summary in enumerate(value.result_summaries, 1)
            )
            return ResponseCompositionDraft(
                schema_version=RESPONSE_COMPOSITION_DRAFT_SCHEMA_VERSION,
                sections=sections,
                referenced_result_ids=value.result_refs,
                referenced_claim_ids=value.claim_refs,
                referenced_citation_ids=value.citation_refs,
                task_status=value.task_status,
            )

        composer = _Composer(omit_acknowledgements)
        output = ResponseCompositionService(composer=composer).compose_aggregation(
            aggregation, request=_request()
        )

        self.assertEqual(1, composer.calls)
        self.assertEqual("rejected", output.observation.outcome)
        self.assertIn("mandatory warning", output.result.answer)
        self.assertIn("alpha | beta", output.result.answer)


if __name__ == "__main__":
    unittest.main()

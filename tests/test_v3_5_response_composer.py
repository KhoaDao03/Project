"""V3.5 response-composer contracts, policy, fallback, and wiring tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from elly.adapters.audit_log import StructuredAuditLog
from elly.adapters.fake_generalist import FakeGeneralist
from elly.adapters.fake_response_composer import (
    FakeResponseComposer,
    ResponseComposerFailureMode,
)
from elly.adapters.ollama_response_composer import OllamaResponseComposer
from elly.adapters.sqlite_repository import SqliteSessionRepository
from elly.adapters.system_clock import FixedClock
from elly.application.presentation_policy import (
    presentation_mode_for_finalization,
    select_presentation_mode,
)
from elly.application.response_composer import (
    compose_blocked,
    compose_cancelled,
    compose_failed,
    compose_partial,
    compose_success,
)
from elly.application.response_pipeline import (
    ResponseCompositionService,
    build_task_response_composition_input,
    validate_response_composition_draft,
)
from elly.composition import Application
from elly.config import load_config
from elly.domain.enums import (
    CloudMode,
    EpistemicStatus,
    PersistenceMode,
    PresentationMode,
    TaskStatus,
    ValidationStatus,
)
from elly.domain.errors import ConfigInvalidError, InputInvalidError, MalformedResultError
from elly.domain.models import TaskRequest
from elly.planning.contracts import FinalizationStrategy
from elly.ports.local_response_composer import (
    RESPONSE_COMPOSITION_DRAFT_SCHEMA_VERSION,
    RESPONSE_COMPOSITION_INPUT_SCHEMA_VERSION,
    MemoryContextPlaceholder,
    PersonalityContextPlaceholder,
    ResponseCompositionDraft,
    ResponseCompositionInput,
    ResponseCompositionRequest,
    ResponseResultSummary,
    ResponseSection,
    ResponseWarningSummary,
)

UTC = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


def _request(request_id: str = "request-1") -> TaskRequest:
    return TaskRequest(
        request_id=request_id,
        session_id="session-1",
        text="Answer the request",
        cloud_mode=CloudMode.LOCAL_ONLY,
        persistence_mode=PersistenceMode.STORE_WITH_RETENTION,
        submitted_at=UTC,
    )


class PresentationPolicyTests(unittest.TestCase):
    def test_substantive_statuses_are_composed(self) -> None:
        for status in (
            TaskStatus.COMPLETED,
            TaskStatus.PARTIAL,
            TaskStatus.BLOCKED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        ):
            self.assertIs(
                PresentationMode.COMPOSED,
                select_presentation_mode(task_status=status),
            )

    def test_protocol_and_exact_modes_are_application_owned(self) -> None:
        self.assertIs(
            PresentationMode.DETERMINISTIC_ONLY,
            select_presentation_mode(
                task_status=TaskStatus.AWAITING_CONSENT,
                protocol_output=True,
            ),
        )
        self.assertIs(
            PresentationMode.EXACT_WITH_COMPOSED_CONTEXT,
            select_presentation_mode(
                task_status=TaskStatus.COMPLETED,
                has_immutable_record=True,
            ),
        )
        self.assertIs(
            PresentationMode.COMPOSED,
            presentation_mode_for_finalization(
                FinalizationStrategy.LOCAL_SYNTHESIS,
                task_status=TaskStatus.COMPLETED,
            ),
        )


class ResponseContractTests(unittest.TestCase):
    def test_inert_context_placeholders_cannot_carry_data(self) -> None:
        self.assertEqual("", PersonalityContextPlaceholder().context_id)
        self.assertEqual("", MemoryContextPlaceholder().context_id)
        with self.assertRaises(InputInvalidError):
            PersonalityContextPlaceholder("future-profile")
        with self.assertRaises(InputInvalidError):
            MemoryContextPlaceholder("future-memory")
        baseline = ResponseCompositionInput(
            schema_version=RESPONSE_COMPOSITION_INPUT_SCHEMA_VERSION,
            task_id="task-placeholder",
            request_text="request",
            presentation_mode=PresentationMode.COMPOSED,
            task_status=TaskStatus.COMPLETED.value,
            result_refs=("result-placeholder",),
        )
        explicit = replace(
            baseline,
            personality_context=PersonalityContextPlaceholder(),
            memory_context=MemoryContextPlaceholder(),
        )
        self.assertIsNone(explicit.personality_context)
        self.assertIsNone(explicit.memory_context)
        self.assertEqual(baseline.to_dict(), explicit.to_dict())

    def test_warning_acknowledgement_is_mandatory(self) -> None:
        composition_input = ResponseCompositionInput(
            schema_version=RESPONSE_COMPOSITION_INPUT_SCHEMA_VERSION,
            task_id="task-1",
            request_text="request",
            presentation_mode=PresentationMode.COMPOSED,
            task_status=TaskStatus.COMPLETED.value,
            result_refs=("result-1",),
            warning_refs=("warning-1",),
            result_summaries=(
                ResponseResultSummary(
                    result_ref="result-1",
                    task_id="task-1",
                    status=TaskStatus.COMPLETED.value,
                    summary="canonical answer",
                    warning_refs=("warning-1",),
                ),
            ),
            warning_summaries=(
                ResponseWarningSummary("warning-1", "task-1", "result-1", "keep this warning"),
            ),
        )
        composer = FakeResponseComposer()
        draft = composer.compose(
            ResponseCompositionRequest("request-1", composition_input, 100, 10.0)
        )
        self.assertIs(draft, validate_response_composition_draft(composition_input, draft))
        with self.assertRaises(MalformedResultError):
            validate_response_composition_draft(
                composition_input,
                replace(draft, acknowledged_warning_ids=()),
            )

    def test_unknown_reference_and_status_mutation_are_rejected(self) -> None:
        result = compose_success(task_id="task-1", answer="canonical")
        composition_input, _ = build_task_response_composition_input(
            result,
            request_text="request",
            request_id="request-1",
        )
        unknown = ResponseCompositionDraft(
            schema_version=RESPONSE_COMPOSITION_DRAFT_SCHEMA_VERSION,
            sections=(ResponseSection("section-1", result_refs=("other-task",)),),
            referenced_result_ids=("other-task",),
        )
        with self.assertRaises(MalformedResultError):
            validate_response_composition_draft(composition_input, unknown)
        good = FakeResponseComposer().compose(
            ResponseCompositionRequest("request-1", composition_input, 100, 10.0)
        )
        with self.assertRaises(MalformedResultError):
            validate_response_composition_draft(
                composition_input,
                replace(good, task_status=TaskStatus.FAILED.value),
            )


class ResponsePipelineTests(unittest.TestCase):
    def test_every_substantive_direct_status_composes_exactly_once(self) -> None:
        cases = (
            compose_success(task_id="task-completed", answer="presentation-ready result"),
            compose_partial(
                task_id="task-partial",
                reason="optional branch failed",
                answer="retained partial result",
            ),
            compose_blocked(task_id="task-blocked", reason="authorization denied"),
            compose_failed(task_id="task-failed", reason="specialist unavailable"),
            compose_cancelled(task_id="task-cancelled", partial_work="retained work"),
        )
        for index, result in enumerate(cases, 1):
            with self.subTest(status=result.task_status):
                composer = FakeResponseComposer()
                output = ResponseCompositionService(composer=composer).compose_task_result(
                    result,
                    request=_request(f"request-substantive-{index}"),
                )
                self.assertEqual(1, len(composer.requests))
                self.assertEqual(result.task_status, output.result.task_status)
                self.assertEqual("accepted", output.observation.outcome)

    def test_composes_once_and_preserves_canonical_claims_and_citations(self) -> None:
        composer = FakeResponseComposer()
        composer.last_output_tokens = 17
        service = ResponseCompositionService(composer=composer)
        result = replace(
            compose_success(task_id="task-1", answer="canonical value"),
            claims=("canonical claim", "second canonical claim"),
            citations=("https://example.test/source",),
            epistemic_status=EpistemicStatus.INFERRED,
            validation_status=ValidationStatus.QUALIFIED,
        )
        pipeline_result = service.compose_task_result(result, request=_request())
        self.assertEqual(1, len(composer.requests))
        self.assertEqual(TaskStatus.COMPLETED, pipeline_result.result.task_status)
        self.assertEqual(EpistemicStatus.INFERRED, pipeline_result.result.epistemic_status)
        self.assertIn("canonical claim", pipeline_result.result.answer)
        self.assertIn("second canonical claim", pipeline_result.result.answer)
        self.assertIn("https://example.test/source", pipeline_result.result.answer)
        self.assertEqual(1, pipeline_result.result.answer.count("https://example.test/source"))
        self.assertEqual(17, pipeline_result.observation.output_tokens)

    def test_citation_without_claim_is_still_rendered_once(self) -> None:
        composer = FakeResponseComposer()
        result = replace(
            compose_success(task_id="task-citation-only", answer="canonical value"),
            citations=("https://example.test/citation-only",),
        )
        output = ResponseCompositionService(composer=composer).compose_task_result(
            result, request=_request("request-citation-only")
        )
        self.assertEqual("accepted", output.observation.outcome)
        self.assertEqual(1, output.result.answer.count("https://example.test/citation-only"))

    def test_ollama_usage_metadata_is_parsed_outside_the_model_draft(self) -> None:
        response_text, output_tokens = OllamaResponseComposer._response_data(
            json.dumps({"response": "{}", "eval_count": 23}).encode("utf-8")
        )
        self.assertEqual("{}", response_text)
        self.assertEqual(23, output_tokens)

    def test_deterministic_only_does_not_call_composer(self) -> None:
        composer = FakeResponseComposer()
        service = ResponseCompositionService(composer=composer)
        result = compose_blocked(task_id="task-1", reason="protocol response")
        output = service.compose_task_result(
            result,
            request=_request(),
            presentation_mode=PresentationMode.DETERMINISTIC_ONLY,
        )
        self.assertFalse(composer.requests)
        self.assertIs(result, output.result)
        self.assertEqual("bypassed", output.observation.outcome)

    def test_composer_failure_falls_back_without_changing_status(self) -> None:
        composer = FakeResponseComposer(failure=ResponseComposerFailureMode.MALFORMED)
        service = ResponseCompositionService(composer=composer)
        result = replace(
            compose_blocked(task_id="task-1", reason="capability unavailable"),
            epistemic_status=EpistemicStatus.BLOCKED,
        )
        output = service.compose_task_result(result, request=_request())
        self.assertEqual(1, len(composer.requests))
        self.assertEqual(result.task_status, output.result.task_status)
        self.assertEqual(result.epistemic_status, output.result.epistemic_status)
        self.assertIn("capability unavailable", output.result.answer)
        self.assertEqual("rejected", output.observation.outcome)

    def test_exact_record_is_inserted_unchanged(self) -> None:
        composer = FakeResponseComposer()
        service = ResponseCompositionService(composer=composer)
        record = "RECEIPT\nbyte-sensitive canonical record\nEND"
        output = service.compose_task_result(
            compose_success(task_id="task-1", answer="action completed"),
            request=_request(),
            immutable_records={"record-1": record},
        )
        self.assertEqual(PresentationMode.EXACT_WITH_COMPOSED_CONTEXT, output.mode)
        self.assertEqual(1, len(composer.requests))
        self.assertIn(record, output.result.answer)
        self.assertEqual(1, output.result.answer.count(record))

    def test_invalid_input_fallback_keeps_exact_record_without_model_call(self) -> None:
        composer = FakeResponseComposer()
        service = ResponseCompositionService(composer=composer)
        record = "RECEIPT\nbyte-sensitive canonical record\nEND"
        output = service.compose_task_result(
            compose_success(task_id="task-1", answer="canonical answer"),
            request=_request(),
            approved_context="approved context " * 20_000,
            immutable_records={"record-1": record},
        )
        self.assertFalse(composer.requests)
        self.assertIn(record, output.result.answer)
        self.assertEqual(1, output.result.answer.count(record))


class ConfigurationAndWiringTests(unittest.TestCase):
    def test_roles_are_independent_and_synthesis_alias_migrates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(
                """
[local_models.profiles.conversation]
provider = "fake"
model_id = "conversation-model"
base_url = "http://127.0.0.1:11434"
timeout_seconds = 10
[local_models.profiles.composer]
provider = "fake"
model_id = "composer-model"
base_url = "http://127.0.0.1:11434"
timeout_seconds = 10
[local_models.roles]
conversation = "conversation"
planner = "conversation"
synthesis = "composer"
[local_models.role_limits]
synthesis_max_output_tokens = 99
""",
                encoding="utf-8",
            )
            config = load_config(str(path))
        self.assertEqual("conversation-model", config.conversation_role.model_id)
        self.assertEqual("composer-model", config.response_composer_role.model_id)
        self.assertEqual(99, config.response_composer_role.max_output_tokens)
        self.assertEqual("response_composer", config.synthesis_role.role)

    def test_conflicting_synthesis_and_response_composer_bindings_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(
                """
[local_models.profiles.one]
provider = "fake"
model_id = "one"
base_url = "http://127.0.0.1:11434"
timeout_seconds = 10
[local_models.profiles.two]
provider = "fake"
model_id = "two"
base_url = "http://127.0.0.1:11434"
timeout_seconds = 10
[local_models.roles]
response_composer = "one"
synthesis = "two"
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigInvalidError):
                load_config(str(path))

    def test_wired_local_turn_uses_one_composer_and_persists_composed_answer(self) -> None:
        repository = SqliteSessionRepository(":memory:")
        repository.apply_migrations()
        composer = FakeResponseComposer()
        app = Application(
            config=load_config(None),
            clock=FixedClock(UTC, step_seconds=1),
            generalist=FakeGeneralist(),
            repository=repository,
            audit=StructuredAuditLog(repository=repository),
            response_composer=composer,
        )
        try:
            session = app.new_session()
            outcome = app.orchestrator.handle(
                replace(_request(), session_id=session.session_id)
            )
            replay = app.orchestrator.handle(
                replace(_request(), session_id=session.session_id)
            )
            self.assertEqual(TaskStatus.COMPLETED, outcome.result.task_status)
            self.assertEqual(1, len(composer.requests))
            self.assertEqual(TaskStatus.PARTIAL, replay.result.task_status)
            self.assertIn("recorded execution", replay.result.failures[0])
            self.assertEqual("assistant", repository.recent_messages(session.session_id, 5)[-1].role)
            self.assertEqual(outcome.result.answer, repository.recent_messages(session.session_id, 5)[-1].content)
        finally:
            app.close()


if __name__ == "__main__":
    unittest.main()

"""Deterministic V3.5 response-composer adapter for tests and offline runs."""

from __future__ import annotations

from enum import Enum
from threading import Event

from ..domain.enums import HealthState
from ..domain.errors import (
    CancelledError,
    MalformedResultError,
    PermanentProviderError,
    ProviderTimeoutError,
    TransientProviderError,
)
from ..domain.models import HealthReport
from ..ports.local_response_composer import (
    RESPONSE_COMPOSITION_DRAFT_SCHEMA_VERSION,
    LocalResponseComposerPort,
    ResponseCompositionDraft,
    ResponseCompositionRequest,
    ResponseSection,
)


class ResponseComposerFailureMode(str, Enum):
    NONE = "none"
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    MALFORMED = "malformed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class FakeResponseComposer(LocalResponseComposerPort):
    """Return a complete reference-only outline without inventing content."""

    def __init__(
        self,
        *,
        failure: ResponseComposerFailureMode = ResponseComposerFailureMode.NONE,
    ) -> None:
        self._failure = failure
        self._cancelled = Event()
        self.requests: list[ResponseCompositionRequest] = []

    def health(self) -> HealthReport:
        return HealthReport(
            component="response_composer(fake)",
            state=HealthState.HEALTHY,
            detail="deterministic fake; not a real model",
        )

    def cancel(self) -> None:
        self._cancelled.set()

    def compose(self, request: ResponseCompositionRequest) -> ResponseCompositionDraft:
        if not isinstance(request, ResponseCompositionRequest):
            raise MalformedResultError("response composer request is invalid")
        if self._cancelled.is_set():
            self._cancelled.clear()
            raise CancelledError("local response composition cancelled")
        self.requests.append(request)
        if self._failure is ResponseComposerFailureMode.TRANSIENT:
            raise TransientProviderError("fake response composer transient failure")
        if self._failure is ResponseComposerFailureMode.PERMANENT:
            raise PermanentProviderError("fake response composer unavailable")
        if self._failure is ResponseComposerFailureMode.TIMEOUT:
            raise ProviderTimeoutError("fake response composer timed out")
        if self._failure is ResponseComposerFailureMode.CANCELLED:
            raise CancelledError("fake response composition cancelled")
        if self._failure is ResponseComposerFailureMode.MALFORMED:
            raise MalformedResultError("fake response composer returned malformed output")

        value = request.composition_input
        sections = tuple(
            ResponseSection(
                section_id=f"section-{index}",
                title="",
                result_refs=(summary.result_ref,),
                claim_refs=summary.claim_refs,
                citation_refs=summary.citation_refs,
                immutable_record_refs=(
                    value.immutable_record_refs if index == 1 else ()
                ),
                narrative="",
            )
            for index, summary in enumerate(value.result_summaries, start=1)
        )
        if not sections:
            # Application builders normally supply a synthetic failed-result
            # reference.  Keeping this explicit makes malformed test inputs
            # fail at the contract boundary rather than inventing a section.
            raise MalformedResultError("response composer input has no result summaries")
        return ResponseCompositionDraft(
            schema_version=RESPONSE_COMPOSITION_DRAFT_SCHEMA_VERSION,
            sections=sections,
            referenced_result_ids=value.result_refs,
            referenced_claim_ids=value.claim_refs,
            referenced_citation_ids=value.citation_refs,
            acknowledged_warning_ids=value.warning_refs,
            acknowledged_disagreement_ids=value.disagreement_refs,
            referenced_immutable_record_ids=value.immutable_record_refs,
            task_status=value.task_status,
        )


# Compatibility spelling used by some adapter factories.
FakeLocalResponseComposer = FakeResponseComposer


__all__ = [
    "FakeLocalResponseComposer",
    "FakeResponseComposer",
    "ResponseComposerFailureMode",
]

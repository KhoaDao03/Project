"""Deterministic local synthesis adapter for offline tests and local defaults."""

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
from ..ports.local_synthesis import (
    SYNTHESIS_DRAFT_SCHEMA_VERSION,
    LocalSynthesisPort,
    SynthesisDraft,
    SynthesisRequest,
    SynthesisSection,
)


class SynthesisFailureMode(str, Enum):
    """Deterministic failure cases used by Phase 7 tests."""

    NONE = "none"
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    MALFORMED = "malformed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class FakeSynthesis(LocalSynthesisPort):
    """Offline synthesizer that references every approved input record."""

    def __init__(self, *, failure: SynthesisFailureMode = SynthesisFailureMode.NONE) -> None:
        self._failure = failure
        self._cancelled = Event()
        self.requests: list[SynthesisRequest] = []

    def health(self) -> HealthReport:
        return HealthReport(
            component="synthesis(fake)",
            state=HealthState.HEALTHY,
            detail="deterministic fake; not a real model",
        )

    def cancel(self) -> None:
        self._cancelled.set()

    def synthesize(self, request: SynthesisRequest) -> SynthesisDraft:
        if not isinstance(request, SynthesisRequest):
            raise MalformedResultError("synthesis request is invalid")
        if self._cancelled.is_set():
            self._cancelled.clear()
            raise CancelledError("local synthesis cancelled")
        self.requests.append(request)
        if self._failure is SynthesisFailureMode.TRANSIENT:
            raise TransientProviderError("fake synthesis transient failure")
        if self._failure is SynthesisFailureMode.PERMANENT:
            raise PermanentProviderError("fake synthesis unavailable")
        if self._failure is SynthesisFailureMode.TIMEOUT:
            raise ProviderTimeoutError("fake synthesis timed out")
        if self._failure is SynthesisFailureMode.CANCELLED:
            raise CancelledError("fake synthesis cancelled")
        if self._failure is SynthesisFailureMode.MALFORMED:
            raise MalformedResultError("fake synthesis returned malformed output")
        sections = tuple(
            SynthesisSection(
                section_id=f"section-{index}",
                title=summary.step_id,
                result_ids=(summary.result_id,),
                claim_ids=summary.claim_ids,
                citation_ids=summary.citation_ids,
            )
            for index, summary in enumerate(request.synthesis_input.step_summaries, start=1)
        )
        return SynthesisDraft(
            schema_version=SYNTHESIS_DRAFT_SCHEMA_VERSION,
            status=request.synthesis_input.plan_status,
            sections=sections,
            included_warning_ids=tuple(
                item.warning_id for item in request.synthesis_input.warnings
            ),
            included_disagreement_ids=tuple(
                item.disagreement_id for item in request.synthesis_input.disagreements
            ),
        )


FakeLocalSynthesis = FakeSynthesis


__all__ = ["FakeLocalSynthesis", "FakeSynthesis", "SynthesisFailureMode"]

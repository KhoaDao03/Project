"""Replayable local synthesis adapter for contract and regression tests."""

from __future__ import annotations

from ..domain.enums import HealthState
from ..domain.errors import MalformedResultError, PermanentProviderError
from ..domain.models import HealthReport
from ..ports.local_synthesis import (
    LocalSynthesisPort,
    SynthesisDraft,
    SynthesisRequest,
    decode_synthesis_draft,
)


class RecordedSynthesis(LocalSynthesisPort):
    """Replay a finite sequence of typed or JSON synthesis drafts."""

    def __init__(
        self,
        responses: tuple[SynthesisDraft | str | bytes, ...],
        *,
        repeat_last: bool = False,
    ) -> None:
        if not isinstance(responses, tuple) or not responses:
            raise MalformedResultError("recorded synthesis requires at least one response")
        self._responses = tuple(
            response if isinstance(response, SynthesisDraft) else decode_synthesis_draft(response)
            for response in responses
        )
        self._repeat_last = repeat_last
        self._index = 0
        self.requests: list[SynthesisRequest] = []

    def health(self) -> HealthReport:
        return HealthReport(component="synthesis(recorded)", state=HealthState.HEALTHY)

    def cancel(self) -> None:
        return None

    def synthesize(self, request: SynthesisRequest) -> SynthesisDraft:
        if not isinstance(request, SynthesisRequest):
            raise MalformedResultError("synthesis request is invalid")
        self.requests.append(request)
        if self._index >= len(self._responses):
            if not self._repeat_last:
                raise PermanentProviderError("recorded synthesis responses are exhausted")
            return self._responses[-1]
        response = self._responses[self._index]
        self._index += 1
        return response


__all__ = ["RecordedSynthesis"]

"""Replayable local response-composer adapter for contract tests."""

from __future__ import annotations

from ..domain.enums import HealthState
from ..domain.errors import MalformedResultError, PermanentProviderError
from ..domain.models import HealthReport
from ..ports.local_response_composer import (
    LocalResponseComposerPort,
    ResponseCompositionDraft,
    ResponseCompositionRequest,
    decode_response_composition_draft,
)


class RecordedResponseComposer(LocalResponseComposerPort):
    """Replay a finite sequence of typed or JSON response drafts."""

    def __init__(
        self,
        responses: tuple[ResponseCompositionDraft | str | bytes, ...],
        *,
        repeat_last: bool = False,
    ) -> None:
        if not isinstance(responses, tuple) or not responses:
            raise MalformedResultError("recorded response composer requires a response")
        self._responses = tuple(
            response
            if isinstance(response, ResponseCompositionDraft)
            else decode_response_composition_draft(response)
            for response in responses
        )
        self._repeat_last = repeat_last
        self._index = 0
        self.requests: list[ResponseCompositionRequest] = []

    def health(self) -> HealthReport:
        return HealthReport(component="response_composer(recorded)", state=HealthState.HEALTHY)

    def cancel(self) -> None:
        return None

    def compose(self, request: ResponseCompositionRequest) -> ResponseCompositionDraft:
        if not isinstance(request, ResponseCompositionRequest):
            raise MalformedResultError("response composer request is invalid")
        self.requests.append(request)
        if self._index >= len(self._responses):
            if not self._repeat_last:
                raise PermanentProviderError("recorded response composer responses are exhausted")
            return self._responses[-1]
        response = self._responses[self._index]
        self._index += 1
        return response


__all__ = ["RecordedResponseComposer"]

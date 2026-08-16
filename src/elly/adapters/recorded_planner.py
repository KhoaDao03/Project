"""Recorded local planner adapter for replayable Phase 2 tests."""

from __future__ import annotations

from ..domain.enums import HealthState
from ..domain.errors import MalformedResultError, PermanentProviderError
from ..domain.models import HealthReport
from ..planning.codec import decode_proposal
from ..planning.contracts import ExecutionProposal
from ..ports.local_planner import PlannerRequest


class RecordedPlanner:
    """Replay a finite sequence of typed or JSON planner responses."""

    def __init__(
        self,
        responses: tuple[ExecutionProposal | str | bytes, ...],
        *,
        repeat_last: bool = False,
    ) -> None:
        if not isinstance(responses, tuple) or not responses:
            raise MalformedResultError("recorded planner requires at least one response")
        self._responses = tuple(
            response if isinstance(response, ExecutionProposal) else decode_proposal(response)
            for response in responses
        )
        self._repeat_last = repeat_last
        self._index = 0
        self.requests: list[PlannerRequest] = []

    def health(self) -> HealthReport:
        return HealthReport(component="planner(recorded)", state=HealthState.HEALTHY)

    def cancel(self) -> None:
        return None

    def propose(self, request: PlannerRequest) -> ExecutionProposal:
        if not isinstance(request, PlannerRequest):
            raise MalformedResultError("planner request is invalid")
        self.requests.append(request)
        if self._index >= len(self._responses):
            if not self._repeat_last:
                raise PermanentProviderError("recorded planner responses are exhausted")
            return self._responses[-1]
        response = self._responses[self._index]
        self._index += 1
        return response


__all__ = ["RecordedPlanner"]

"""Deterministic fake local planner for Phase 2 contract tests."""

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
from ..planning.codec import decode_proposal
from ..planning.contracts import (
    PROPOSAL_SCHEMA_VERSION,
    ExecutionProposal,
    FinalizationStrategy,
    ProposalDisposition,
)
from ..ports.local_planner import PlannerRequest


class PlannerFailureMode(str, Enum):
    """Deterministic planner failure scenarios used by tests."""

    NONE = "none"
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    MALFORMED = "malformed"
    TIMEOUT = "timeout"


def local_only_proposal() -> ExecutionProposal:
    """Return the safe default proposal used by the fake adapter."""
    return ExecutionProposal(
        schema_version=PROPOSAL_SCHEMA_VERSION,
        disposition=ProposalDisposition.LOCAL_ONLY,
        steps=(),
        finalization=FinalizationStrategy.DIRECT,
        ambiguities=(),
        confidence=1.0,
        reason_code="FAKE_LOCAL_ONLY",
        justification="deterministic local-only test proposal",
    )


class FakePlanner:
    """Offline planner that returns a configured proposal and never executes work."""

    def __init__(
        self,
        proposal: ExecutionProposal | str | bytes | None = None,
        *,
        failure: PlannerFailureMode = PlannerFailureMode.NONE,
    ) -> None:
        if proposal is None:
            self._proposal = local_only_proposal()
        elif isinstance(proposal, ExecutionProposal):
            self._proposal = proposal
        else:
            self._proposal = decode_proposal(proposal)
        self._failure = failure
        self.requests: list[PlannerRequest] = []
        self._cancelled = Event()

    def health(self) -> HealthReport:
        return HealthReport(
            component="planner(fake)",
            state=HealthState.HEALTHY,
            detail="deterministic fake; not a real model",
        )

    def cancel(self) -> None:
        self._cancelled.set()

    def propose(self, request: PlannerRequest) -> ExecutionProposal:
        if not isinstance(request, PlannerRequest):
            raise MalformedResultError("planner request is invalid")
        if self._cancelled.is_set():
            self._cancelled.clear()
            raise CancelledError("local planning cancelled")
        self.requests.append(request)
        if self._failure is PlannerFailureMode.TRANSIENT:
            raise TransientProviderError("fake planner transient failure")
        if self._failure is PlannerFailureMode.PERMANENT:
            raise PermanentProviderError("fake planner unavailable")
        if self._failure is PlannerFailureMode.TIMEOUT:
            raise ProviderTimeoutError("fake planner timed out")
        if self._failure is PlannerFailureMode.MALFORMED:
            raise MalformedResultError("fake planner returned malformed output")
        return self._proposal


__all__ = ["FakePlanner", "PlannerFailureMode", "local_only_proposal"]

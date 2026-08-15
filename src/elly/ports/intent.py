"""Intent interpretation port used by deterministic or future model adapters."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import CapabilityIntent, RouteProposal, RouteRequest


@runtime_checkable
class IntentInterpreterPort(Protocol):
    """Translate untrusted request text/proposals into a typed intent."""

    def interpret(
        self,
        request: RouteRequest,
        *,
        proposal: RouteProposal | None = None,
    ) -> CapabilityIntent:
        ...

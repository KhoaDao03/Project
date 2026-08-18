"""FakeGeneralist — DETERMINISTIC FAKE generalist adapter (test support).

⚠️ THIS IS A TEST/DEVELOPMENT FAKE, NOT A PRODUCTION CAPABILITY. It does no
inference and no network I/O. It exercises the full path (CLI -> runtime ->
capability -> port -> storage/audit) without depending on Ollama. The real
Ollama adapter implements the same
`GeneralistPort` and replace this via the composition root + config.

Determinism: given the same GeneralistRequest, `generate` returns the same
GeneralistResponse (no randomness, no clock use, no hidden mutable global state).

Failure injection: construct with a `FailureMode` to make `generate` deterministically
raise a typed provider error or return malformed output, so failure mapping
(FR-006/NFR-002) is testable before any real provider exists.

Security: returns plain text only, treated by the local capability as an untrusted
PROPOSAL (SEC-003/SEC-005). Holds no secrets.

Related: AI-001 (interface only; capability is fake), API-001, NFR-002, NFR-006.
"""

from __future__ import annotations

from enum import Enum

from ..domain.enums import HealthState
from ..domain.errors import (
    MalformedResultError,
    PermanentProviderError,
    TransientProviderError,
)
from ..domain.models import (
    GeneralistRequest,
    GeneralistResponse,
    GeneralistUsage,
    HealthReport,
)

_FAKE_PREFIX = "[fake-generalist] "


class FailureMode(str, Enum):
    """Deterministic failure scenarios for testing (not production behavior)."""

    NONE = "none"
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    MALFORMED = "malformed"
    UNHEALTHY = "unhealthy"


class FakeGeneralist:
    """A deterministic, offline stand-in for the local generalist model.

    Implements `ports.generalist.GeneralistPort`.
    """

    def __init__(
        self, model_id: str = "fake-generalist-v1", failure: FailureMode = FailureMode.NONE
    ) -> None:
        self._model_id = model_id
        self._failure = failure

    # -- GeneralistPort ---------------------------------------------------

    def health(self) -> HealthReport:
        if self._failure is FailureMode.UNHEALTHY:
            return HealthReport(
                component="generalist(fake)",
                state=HealthState.UNAVAILABLE,
                detail="fake configured UNHEALTHY",
            )
        return HealthReport(
            component="generalist(fake)",
            state=HealthState.HEALTHY,
            detail="deterministic fake; not a real model",
        )

    def generate(self, request: GeneralistRequest) -> GeneralistResponse:
        """Return a deterministic response, or raise a typed error per failure mode."""
        if self._failure is FailureMode.TRANSIENT:
            raise TransientProviderError("fake transient failure")
        if self._failure is FailureMode.PERMANENT:
            raise PermanentProviderError("fake permanent failure")
        if self._failure is FailureMode.MALFORMED:
            # Empty output violates the contract; the capability must reject it.
            raise MalformedResultError("fake produced empty output")

        # Deterministic, obviously-synthetic reply. Echoes a bounded slice of the
        # prompt so multi-turn context wiring is visible in tests/demos, while the
        # prefix makes clear this is not a real answer.
        snippet = request.prompt.strip().splitlines()[-1] if request.prompt.strip() else ""
        snippet = snippet[:200]
        text = (
            f"{_FAKE_PREFIX}acknowledged: {snippet}" if snippet else f"{_FAKE_PREFIX}acknowledged."
        )
        usage = GeneralistUsage(
            output_tokens=min(len(text.split()), request.max_output_tokens), latency_ms=0
        )
        return GeneralistResponse(text=text, usage=usage)

    def cancel(self) -> None:
        """The deterministic fake has no active I/O to interrupt."""
        return None

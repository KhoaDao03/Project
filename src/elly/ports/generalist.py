"""GeneralistPort — the local generalist model contract (DESIGN §6.7).

Responsibility: abstract "produce text from a bounded prompt" so the application
never depends on a concrete model runtime.

Runtime adapters:
- `adapters.ollama_generalist.OllamaGeneralist` is the real localhost adapter.
- `adapters.fake_generalist.FakeGeneralist` is retained for deterministic tests.

Replacement strategy: because callers depend only on this Protocol, swapping the
fake for the Ollama adapter in M2 is a composition-root change plus config — no
change to application/domain code (NFR-006, AT-02.4/AT-03.5 target).

Contract:
- inputs: GeneralistRequest (bounded prompt + model_id + max_output_tokens).
- outputs: GeneralistResponse (normalized text + usage). Text is UNTRUSTED
  model output and must be treated as a proposal, never an instruction
  (SEC-003/SEC-005). Validation is the application capability's job, not the
  adapter's.
- failures: typed EllyError subclasses only (TransientProviderError,
  PermanentProviderError, MalformedResultError). Provider-specific exceptions
  must NOT cross this boundary.
- side effects: may perform I/O in real adapters; the M1 fake performs none.
- security: no secret handling in M1 (fake). Real adapters resolve credentials at
  their own boundary and never serialize them (SEC-004).

Related: AI-001, API-001, NFR-002, NFR-006.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import GeneralistRequest, GeneralistResponse, HealthReport


@runtime_checkable
class GeneralistPort(Protocol):
    """Contract for a local generalist model provider."""

    def health(self) -> HealthReport:
        """Report readiness without performing a generation (OPS-002)."""
        ...

    def generate(self, request: GeneralistRequest) -> GeneralistResponse:
        """Produce a normalized response, or raise a typed EllyError on failure."""
        ...

    def cancel(self) -> None:
        """Request cancellation; adapters without active work may no-op."""
        ...

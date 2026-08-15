"""Explicit domain errors for Elly (DESIGN §6.8 error taxonomy).

Responsibility: give every failure a typed class carrying an `ErrorClass`, so the
orchestrator and audit layer map failures deterministically instead of leaking
provider-specific exceptions upward (NFR-002, NFR-006).

Security/privacy: error messages must be SAFE FOR DISPLAY/LOG — never include
secrets, raw prompts, message bodies, or chain-of-thought (SEC-004, SEC-007).
Callers construct these with short, non-sensitive summaries only.

Status: Implemented for the M3 guardrail path. The taxonomy remains extensible for
later provider capabilities; see `enums.ErrorClass` for the complete classification.

Non-responsibilities: retry/backoff policy is owned by the guardrail controller;
these classes remain pure data-carrying exceptions.
"""

from __future__ import annotations

from .enums import ErrorClass


class EllyError(Exception):
    """Base class for all typed Elly domain errors.

    Attributes:
        error_class: the taxonomy member (ErrorClass) for deterministic mapping.
        summary: short, non-sensitive, display/log-safe description.
    """

    error_class: ErrorClass = ErrorClass.CONFIG_INVALID  # overridden by subclasses

    def __init__(self, summary: str) -> None:
        if not summary or not summary.strip():
            summary = self.error_class.value
        self.summary = summary.strip()
        super().__init__(f"[{self.error_class.value}] {self.summary}")


class InputInvalidError(EllyError):
    """Untrusted input failed boundary validation (FR-001, SEC-006 input side)."""

    error_class = ErrorClass.INPUT_INVALID


class ConfigInvalidError(EllyError):
    """Configuration missing/invalid; fail closed for the affected capability (OPS-002)."""

    error_class = ErrorClass.CONFIG_INVALID


class PermissionDeniedError(EllyError):
    """A capability is not permitted in the current mode/milestone (SEC-005/AI-014)."""

    error_class = ErrorClass.PERMISSION_DENIED


class ConsentRequiredError(EllyError):
    """A cloud call is eligible but awaits an exact owner approval."""

    error_class = ErrorClass.PERMISSION_DENIED

    def __init__(self, summary: str, *, proposal: object) -> None:
        super().__init__(summary)
        self.proposal = proposal


class StorageFailureError(EllyError):
    """Persistence transaction failed; no hidden continuation (DATA-001)."""

    error_class = ErrorClass.STORAGE_FAILURE


class ConflictError(EllyError):
    """A compare-and-set operation lost a concurrent update."""

    error_class = ErrorClass.CONFLICT


class LimitExceededError(EllyError):
    """A configured resource or budget ceiling was reached."""

    error_class = ErrorClass.LIMIT_EXCEEDED


class CircuitOpenError(EllyError):
    """A dependency circuit is open after repeated transient failures."""

    error_class = ErrorClass.PERMANENT_PROVIDER


class UnsafeUrlError(EllyError):
    """A provider citation failed application-side URL policy (SEC-006)."""

    error_class = ErrorClass.UNSAFE_URL


class UnsupportedContentError(EllyError):
    """A provider returned content outside the approved evidence contract."""

    error_class = ErrorClass.UNSUPPORTED_CONTENT


class MalformedResultError(EllyError):
    """A provider/model result violated its contract (AI-007/AI-011)."""

    error_class = ErrorClass.MALFORMED_RESULT


class TransientProviderError(EllyError):
    """A provider failed in a possibly-retryable way (NFR-002)."""

    error_class = ErrorClass.TRANSIENT_PROVIDER


class PermanentProviderError(EllyError):
    """A provider failed unrecoverably (e.g., unavailable) (NFR-002)."""

    error_class = ErrorClass.PERMANENT_PROVIDER


class AuthenticationProviderError(PermanentProviderError):
    """Provider credentials are missing, invalid, or unauthorized."""


class ModelUnavailableError(PermanentProviderError):
    """The configured provider model does not exist or is inaccessible."""


class ProviderQuotaError(PermanentProviderError):
    """The account has no usable provider quota; immediate retry is unsafe."""


class RateLimitProviderError(TransientProviderError):
    """The provider rate-limited a call that may be retried under policy."""


class ProviderTimeoutError(EllyError):
    """The local provider exceeded its configured call timeout."""

    error_class = ErrorClass.TIMEOUT


class CancelledError(EllyError):
    """The owner cancelled an in-flight local operation."""

    error_class = ErrorClass.CANCELLED

    def __init__(self, summary: str, *, partial_work: str = "") -> None:
        super().__init__(summary)
        self.partial_work = partial_work

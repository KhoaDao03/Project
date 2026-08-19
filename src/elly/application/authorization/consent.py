"""Deterministic authorization for external capability calls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ...domain.enums import CloudMode
from ...domain.errors import ConfigInvalidError
from ...privacy import (
    ClassificationDecision,
    ConsentProposal,
    ConsentWorkflow,
    PrivacyClass,
    payload_hash,
)


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    """Safe authorization result; it contains no protected payload."""

    allowed: bool
    reason_code: str
    classification: PrivacyClass
    payload_digest: str
    consent_proposal: ConsentProposal | None = None


@dataclass(frozen=True, slots=True)
class CloudAuthorizationRequest:
    """Immutable, provider-independent input to cloud boundary authorization."""

    task_id: str
    payload: str
    classification: ClassificationDecision | None
    cloud_mode: CloudMode
    destination: str
    model: str
    capability_id: str
    purpose: str
    consent: ConsentWorkflow | None
    approval_id: str | None
    max_cost: float
    now: datetime
    capability_available: bool = True
    requires_external_boundary: bool = True
    plan_id: str = ""
    step_id: str = ""
    operation: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ConfigInvalidError("authorization task_id is required")
        if not isinstance(self.payload, str) or not self.payload.strip():
            raise ConfigInvalidError("authorization payload must be non-empty")
        if self.classification is not None and not isinstance(
            self.classification, ClassificationDecision
        ):
            raise ConfigInvalidError("authorization classification is invalid")
        if not isinstance(self.cloud_mode, CloudMode):
            raise ConfigInvalidError("authorization cloud_mode must be a CloudMode")
        if not isinstance(self.capability_id, str) or not self.capability_id.strip():
            raise ConfigInvalidError("authorization capability is required")
        if not isinstance(self.destination, str) or not isinstance(self.model, str):
            raise ConfigInvalidError("authorization destination and model must be text")
        if not isinstance(self.purpose, str) or not self.purpose.strip():
            raise ConfigInvalidError("authorization purpose is required")
        if self.consent is not None and not isinstance(self.consent, ConsentWorkflow):
            raise ConfigInvalidError("authorization consent must be a ConsentWorkflow")
        if not isinstance(self.max_cost, (int, float)) or self.max_cost < 0:
            raise ConfigInvalidError("authorization max_cost must not be negative")
        if not isinstance(self.now, datetime) or self.now.tzinfo is None:
            raise ConfigInvalidError("authorization now must be timezone-aware")
        if not isinstance(self.capability_available, bool):
            raise ConfigInvalidError("authorization capability_available must be a bool")
        if not isinstance(self.requires_external_boundary, bool):
            raise ConfigInvalidError("authorization requires_external_boundary must be a bool")
        for value, name in (
            (self.plan_id, "authorization plan_id"),
            (self.step_id, "authorization step_id"),
            (self.operation, "authorization operation"),
        ):
            if not isinstance(value, str):
                raise ConfigInvalidError(f"{name} must be text")
        if self.requires_external_boundary and (
            not self.destination.strip() or not self.model.strip()
        ):
            raise ConfigInvalidError("external authorization destination and model are required")


class CloudAuthorizationPolicy:
    """Separates classification from permission to cross an external boundary."""

    def authorize(self, request: CloudAuthorizationRequest) -> AuthorizationDecision:
        """Return a safe, deterministic decision for one external-boundary request."""
        if not isinstance(request, CloudAuthorizationRequest):
            raise ConfigInvalidError("cloud authorization requires a typed request")

        digest = payload_hash(request.payload)
        privacy = (
            request.classification.classification
            if request.classification is not None
            else PrivacyClass.UNCLASSIFIED
        )
        if not request.requires_external_boundary:
            return AuthorizationDecision(True, "LOCAL_BOUNDARY", privacy, digest)
        if request.classification is None:
            return AuthorizationDecision(False, "CLASSIFICATION_UNAVAILABLE", privacy, digest)
        if not request.capability_available:
            return AuthorizationDecision(False, "CAPABILITY_UNAVAILABLE", privacy, digest)
        if request.cloud_mode is not CloudMode.CLOUD_PERMITTED:
            return AuthorizationDecision(False, "CLOUD_MODE_DENIED", privacy, digest)
        if privacy is PrivacyClass.RESTRICTED:
            return AuthorizationDecision(False, "RESTRICTED_CONTENT", privacy, digest)
        if privacy is PrivacyClass.UNCLASSIFIED:
            return AuthorizationDecision(False, "UNCLASSIFIED_CONTENT", privacy, digest)
        categories = (privacy.value,)
        if privacy is PrivacyClass.LOCAL:
            if request.consent is None:
                return AuthorizationDecision(
                    False, "CONSENT_CAPABILITY_UNAVAILABLE", privacy, digest
                )
            if request.consent.check(
                proposal_id=request.approval_id,
                payload=request.payload,
                provider=request.destination,
                model=request.model,
                purpose=request.purpose,
                capability_id=request.capability_id,
                plan_id=request.plan_id,
                step_id=request.step_id,
                operation=request.operation,
                categories=categories,
                max_cost=request.max_cost,
                now=request.now,
            ):
                return AuthorizationDecision(True, "EXACT_CONSENT_VALID", privacy, digest)
            proposal = request.consent.propose(
                task_id=request.task_id,
                provider=request.destination,
                model=request.model,
                purpose=request.purpose,
                capability_id=request.capability_id,
                plan_id=request.plan_id,
                step_id=request.step_id,
                operation=request.operation,
                payload=request.payload,
                categories=categories,
                max_cost=request.max_cost,
                now=request.now,
            )
            return AuthorizationDecision(
                False,
                "EXACT_CONSENT_REQUIRED",
                privacy,
                digest,
                consent_proposal=proposal,
            )
        return AuthorizationDecision(True, "PUBLIC_PAYLOAD_ALLOWED", privacy, digest)

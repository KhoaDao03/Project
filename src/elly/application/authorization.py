"""Deterministic authorization for external capability calls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..domain.enums import CloudMode
from ..domain.errors import ConfigInvalidError
from ..privacy import (
    ClassificationDecision,
    ConsentProposal,
    ConsentWorkflow,
    PrivacyClass,
)


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    """Safe authorization result; it contains no protected payload."""

    allowed: bool
    reason_code: str
    classification: PrivacyClass
    payload_digest: str
    consent_proposal: ConsentProposal | None = None


class CloudAuthorizationPolicy:
    """Separates classification from permission to cross an external boundary."""

    def authorize(
        self,
        *,
        task_id: str,
        payload: str,
        classification: ClassificationDecision,
        cloud_mode: CloudMode,
        destination: str,
        model: str,
        capability_id: str,
        purpose: str,
        consent: ConsentWorkflow | None,
        approval_id: str | None,
        max_cost: float,
        now: datetime,
        capability_available: bool = True,
        requires_external_boundary: bool = True,
    ) -> AuthorizationDecision:
        if not isinstance(classification, ClassificationDecision):
            raise ConfigInvalidError("authorization requires a classification decision")
        if not capability_id.strip():
            raise ConfigInvalidError("authorization capability is required")
        if requires_external_boundary and (not destination.strip() or not model.strip()):
            raise ConfigInvalidError(
                "external authorization destination and model are required"
            )
        if max_cost < 0:
            raise ConfigInvalidError("authorization max_cost must not be negative")
        from ..privacy import payload_hash

        digest = payload_hash(payload)
        privacy = classification.classification
        if not requires_external_boundary:
            return AuthorizationDecision(True, "LOCAL_BOUNDARY", privacy, digest)
        if not capability_available:
            return AuthorizationDecision(False, "CAPABILITY_UNAVAILABLE", privacy, digest)
        if cloud_mode is not CloudMode.CLOUD_PERMITTED:
            return AuthorizationDecision(False, "CLOUD_MODE_DENIED", privacy, digest)
        if privacy is PrivacyClass.RESTRICTED:
            return AuthorizationDecision(False, "RESTRICTED_CONTENT", privacy, digest)
        if privacy is PrivacyClass.UNCLASSIFIED:
            return AuthorizationDecision(False, "UNCLASSIFIED_CONTENT", privacy, digest)
        categories = (privacy.value,)
        if privacy is PrivacyClass.LOCAL:
            if consent is None:
                return AuthorizationDecision(False, "CONSENT_CAPABILITY_UNAVAILABLE", privacy, digest)
            if consent.check(
                proposal_id=approval_id,
                payload=payload,
                provider=destination,
                model=model,
                purpose=purpose,
                capability_id=capability_id,
                categories=categories,
                max_cost=max_cost,
                now=now,
            ):
                return AuthorizationDecision(True, "EXACT_CONSENT_VALID", privacy, digest)
            proposal = consent.propose(
                task_id=task_id,
                provider=destination,
                model=model,
                purpose=purpose,
                capability_id=capability_id,
                payload=payload,
                categories=categories,
                max_cost=max_cost,
                now=now,
            )
            return AuthorizationDecision(
                False,
                "EXACT_CONSENT_REQUIRED",
                privacy,
                digest,
                consent_proposal=proposal,
            )
        return AuthorizationDecision(True, "PUBLIC_PAYLOAD_ALLOWED", privacy, digest)

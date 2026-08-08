"""M5 privacy classification and exact-consent primitives (DEC-OQ-06)."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from .domain.errors import ConfigInvalidError, PermissionDeniedError


class PrivacyClass(str, Enum):
    LOCAL = "local"
    REMOTE_ALLOWED = "remote_allowed"
    RESTRICTED = "restricted"
    UNCLASSIFIED = "unclassified"


@dataclass(frozen=True, slots=True)
class ClassificationDecision:
    """What a payload is, without implying that it may be transmitted."""

    classification: PrivacyClass
    reason_code: str

    def __post_init__(self) -> None:
        if not isinstance(self.classification, PrivacyClass):
            raise ConfigInvalidError("classification must be a PrivacyClass")
        if not isinstance(self.reason_code, str) or not self.reason_code.strip():
            raise ConfigInvalidError("classification reason_code must be non-empty")

    @property
    def is_external_eligible(self) -> bool:
        return self.classification is PrivacyClass.REMOTE_ALLOWED


_SECRET = re.compile(r"(?i)(api[_ -]?key|secret|password|token|-----begin .*private key-----)")
_SECRET_VALUE = re.compile(
    r"(?i)\b(api[_ -]?key|secret|password|token)\b\s*[:=]\s*([^\s,;]+)"
)
_PRIVATE_KEY = re.compile(
    r"(?is)-----begin [^-\r\n]*private key-----.*?-----end [^-\r\n]*private key-----"
)
_LOCAL = re.compile(r"(?i)\b(my|mine|private|personal|internal|confidential|home|family|employee|client)\b")
_PUBLIC = re.compile(
    r"(?i)\b(public|open[ -]?source|published|official|documentation|rfc|"
    r"current|latest|weather|news|stock[ -]?market|market[ -]?index|"
    r"s\s*&\s*p\s*500|sp500|dow\s+jones|nasdaq|"
    r"commodity|commodities|spot[ -]?price|futures?[ -]?price|"
    r"gold|silver|platinum|palladium|copper|crude[ -]?oil|brent|wti|"
    r"natural[ -]?gas|exchange[ -]?rate|forex|currency[ -]?rate|"
    r"bitcoin|ethereum|cryptocurrency|bond[ -]?yield|treasury[ -]?yield)\b"
)


def classify_payload(text: str) -> PrivacyClass:
    """Classify the complete outgoing text conservatively, before any provider call."""
    if not isinstance(text, str) or not text.strip():
        raise ConfigInvalidError("specialist payload must be non-empty text")
    if _SECRET.search(text):
        return PrivacyClass.RESTRICTED
    if _LOCAL.search(text):
        return PrivacyClass.LOCAL
    if _PUBLIC.search(text):
        return PrivacyClass.REMOTE_ALLOWED
    return PrivacyClass.UNCLASSIFIED


class PrivacyPolicy:
    """Application-owned, deterministic payload classification."""

    def classify(self, payload: str) -> ClassificationDecision:
        classification = classify_payload(payload)
        reason = {
            PrivacyClass.RESTRICTED: "RESTRICTED_CONTENT",
            PrivacyClass.LOCAL: "OWNER_SPECIFIC_CONTENT",
            PrivacyClass.REMOTE_ALLOWED: "PUBLIC_CONTENT",
            PrivacyClass.UNCLASSIFIED: "NO_SAFE_CLASSIFICATION",
        }[classification]
        return ClassificationDecision(classification, reason)


def payload_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ConsentProposal:
    proposal_id: str
    task_id: str
    provider: str
    model: str
    purpose: str
    categories: tuple[str, ...]
    redacted_preview: str
    payload_digest: str
    max_reserved_cost: float
    created_at: datetime
    expires_at: datetime
    capability_id: str = ""


@dataclass(frozen=True, slots=True)
class Approval:
    proposal_id: str
    payload_digest: str
    decision: str
    approved_at: datetime
    interface: str


class ConsentWorkflow:
    """In-memory exact one-time approval store; no payload bodies are retained."""

    def __init__(self, *, ttl_seconds: int = 300) -> None:
        if ttl_seconds <= 0:
            raise ConfigInvalidError("consent TTL must be positive")
        self._ttl = ttl_seconds
        self._proposals: dict[str, ConsentProposal] = {}
        self._approvals: dict[str, Approval] = {}

    def propose(self, *, task_id: str, provider: str, model: str, purpose: str,
                payload: str, categories: tuple[str, ...], max_cost: float,
                capability_id: str = "",
                now: datetime | None = None) -> ConsentProposal:
        stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        proposal = ConsentProposal(
            proposal_id=f"consent-{secrets.token_hex(8)}", task_id=task_id,
            provider=provider, model=model, purpose=purpose, categories=categories,
            redacted_preview=_preview(payload), payload_digest=payload_hash(payload),
            max_reserved_cost=max_cost, created_at=stamp,
            expires_at=stamp + timedelta(seconds=self._ttl),
            capability_id=capability_id,
        )
        self._proposals[proposal.proposal_id] = proposal
        return proposal

    def approve(self, proposal_id: str, *, interface: str = "cli", now: datetime | None = None) -> Approval:
        proposal = self._proposals.get(proposal_id)
        stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if proposal is None or stamp >= proposal.expires_at:
            raise PermissionDeniedError("consent proposal is missing or expired")
        approval = Approval(proposal_id, proposal.payload_digest, "approved", stamp, interface)
        self._approvals[proposal_id] = approval
        return approval

    def deny(self, proposal_id: str, *, interface: str = "cli", now: datetime | None = None) -> Approval:
        proposal = self._proposals.get(proposal_id)
        stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if proposal is None:
            raise PermissionDeniedError("consent proposal is missing")
        approval = Approval(proposal_id, proposal.payload_digest, "denied", stamp, interface)
        self._approvals[proposal_id] = approval
        return approval

    def check(self, *, proposal_id: str | None, payload: str, provider: str | None = None,
              model: str | None = None, purpose: str | None = None,
              capability_id: str | None = None,
              categories: tuple[str, ...] | None = None, max_cost: float | None = None,
              now: datetime | None = None) -> bool:
        """Consume an exact, unexpired approval bound to all supplied call fields."""
        if not proposal_id:
            return False
        proposal = self._proposals.get(proposal_id)
        approval = self._approvals.get(proposal_id)
        stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        valid = bool(
            proposal and approval and approval.decision == "approved"
            and stamp < proposal.expires_at
            and approval.payload_digest == payload_hash(payload)
            and proposal.payload_digest == approval.payload_digest
            and (provider is None or proposal.provider == provider)
            and (model is None or proposal.model == model)
            and (purpose is None or proposal.purpose == purpose)
            and (capability_id is None or proposal.capability_id == capability_id)
            and (categories is None or proposal.categories == categories)
            and (max_cost is None or proposal.max_reserved_cost == max_cost)
        )
        if valid:
            # Exact consent is one-shot. Retaining the proposal supports audit/UI,
            # while removing approval authority prevents replay.
            self._approvals.pop(proposal_id, None)
        return valid


def _preview(payload: str) -> str:
    redacted = _PRIVATE_KEY.sub("[REDACTED PRIVATE KEY]", payload)
    redacted = _SECRET_VALUE.sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)
    redacted = _SECRET.sub("[REDACTED]", redacted)
    return " ".join(redacted.split())[:240]

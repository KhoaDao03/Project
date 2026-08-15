"""Typed, deterministic authorization for consequential action proposals.

This module deliberately separates three concerns:

* ``ActionProposal`` is untrusted structured data;
* ``ActionAuthorizationPolicy`` validates semantics and computes the minimum
  risk that must be enforced; and
* ``ActionConfirmationWorkflow`` stores one-time, target-bound approvals.

No provider or state-changing adapter is called here.  V2 Phase 5 defines the
authorization boundary while the effectful actions excluded by the Phase 0
freeze remain unavailable.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..domain.enums import (
    ActionCategory,
    ActionDataSensitivity,
    ActionImpactFlag,
    ActionProposalSource,
    ActionReversibility,
    ActionSideEffect,
)
from ..domain.errors import ConfigInvalidError, InputInvalidError, PermissionDeniedError
from ..domain.models import ActionConfirmationProposal, ActionProposal, ActionTarget


@dataclass(frozen=True, slots=True)
class ActionPolicyDecision:
    """Pure risk assessment before an approval is considered."""

    allowed: bool
    reason_code: str
    proposal: ActionProposal
    action_digest: str
    confirmation_required: bool = False


@dataclass(frozen=True, slots=True)
class ActionAuthorizationRequest:
    """Immutable input to the approval-aware action authorization service."""

    task_id: str
    capability_id: str
    operation: str
    proposal: ActionProposal
    declared_action: ActionProposal | None = None
    confirmation_id: str | None = None
    now: datetime | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.task_id, "task_id"),
            (self.capability_id, "capability_id"),
            (self.operation, "operation"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ConfigInvalidError(f"action authorization {name} is required")
        if not isinstance(self.proposal, ActionProposal):
            raise ConfigInvalidError("action authorization proposal is invalid")
        if self.declared_action is not None and not isinstance(
            self.declared_action, ActionProposal
        ):
            raise ConfigInvalidError("declared action proposal is invalid")
        if self.confirmation_id is not None and not self.confirmation_id.strip():
            raise ConfigInvalidError("action confirmation_id must be non-empty")
        if self.now is not None and (
            not isinstance(self.now, datetime) or self.now.tzinfo is None
        ):
            raise ConfigInvalidError("action authorization now must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ActionAuthorizationDecision:
    """Safe result of policy plus exact confirmation validation."""

    allowed: bool
    reason_code: str
    proposal: ActionProposal
    action_digest: str
    confirmation_proposal: ActionConfirmationProposal | None = None


@dataclass(frozen=True, slots=True)
class ActionApproval:
    confirmation_id: str
    action_digest: str
    decision: str
    approved_at: datetime
    interface: str


_REQUIRED_FLAGS = {
    ActionCategory.EXTERNAL_COMMUNICATION: ActionImpactFlag.COMMUNICATION,
    ActionCategory.DELETE: ActionImpactFlag.DELETION,
    ActionCategory.FINANCIAL_TRANSACTION: ActionImpactFlag.FINANCIAL,
    ActionCategory.ACCOUNT_CHANGE: ActionImpactFlag.ACCOUNT,
}
_TARGET_REQUIRED = frozenset(
    {
        ActionCategory.EXTERNAL_COMMUNICATION,
        ActionCategory.DELETE,
        ActionCategory.FINANCIAL_TRANSACTION,
        ActionCategory.ACCOUNT_CHANGE,
        ActionCategory.EXTERNAL_WRITE,
        ActionCategory.IRREVERSIBLE_OPERATION,
    }
)
_SECRET_VALUE = re.compile(
    r"(?i)\b(api[_ -]?key|secret|password|token)\b\s*[:=]\s*([^\s,;]+)"
)
_RISK_RANK = {
    ActionCategory.NONE: 0,
    ActionCategory.CONTENT_DRAFT: 1,
    ActionCategory.EXTERNAL_WRITE: 2,
    ActionCategory.EXTERNAL_COMMUNICATION: 3,
    ActionCategory.ACCOUNT_CHANGE: 4,
    ActionCategory.FINANCIAL_TRANSACTION: 5,
    ActionCategory.DELETE: 6,
    ActionCategory.IRREVERSIBLE_OPERATION: 7,
}


def normalized_action_digest(proposal: ActionProposal) -> str:
    """Hash only normalized action metadata, never the action payload."""

    if not isinstance(proposal, ActionProposal):
        raise ConfigInvalidError("action digest requires an ActionProposal")
    target = None
    if proposal.target is not None:
        target = {
            "kind": proposal.target.normalized[0],
            "reference": proposal.target.normalized[1],
        }
    normalized = {
        "category": proposal.category.value,
        "target": target,
        "side_effect": proposal.side_effect.value,
        "reversibility": proposal.reversibility.value,
        "data_sensitivity": proposal.data_sensitivity.value,
        "impact_flags": sorted(flag.value for flag in proposal.impact_flags),
        "confirmation_required": bool(proposal.confirmation_required),
    }
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def safe_action_target_reference(target: ActionTarget | None) -> str:
    """Render only bounded target metadata for a public result or audit detail."""
    if target is None:
        return "unspecified"
    redacted = _SECRET_VALUE.sub(lambda match: f"{match.group(1)}=[REDACTED]", target.reference)
    return " ".join(redacted.split())[:120]


class ActionAuthorizationPolicy:
    """Pure deterministic semantic risk policy."""

    def evaluate(
        self,
        proposal: ActionProposal,
        *,
        declared_action: ActionProposal | None = None,
    ) -> ActionPolicyDecision:
        if not isinstance(proposal, ActionProposal):
            raise ConfigInvalidError("action policy requires an ActionProposal")
        if declared_action is not None and not isinstance(declared_action, ActionProposal):
            raise ConfigInvalidError("declared action must be an ActionProposal")

        try:
            effective = self._apply_declared_minimum(proposal, declared_action)
        except _UndeclaredActionError:
            return ActionPolicyDecision(
                False,
                "UNDECLARED_SIDE_EFFECT",
                proposal,
                normalized_action_digest(proposal),
            )
        digest = normalized_action_digest(effective)
        if effective.category is ActionCategory.NONE:
            return ActionPolicyDecision(True, "NO_SIDE_EFFECT", effective, digest)
        if effective.category is ActionCategory.CONTENT_DRAFT:
            if effective.side_effect is not ActionSideEffect.NONE:
                return self._deny(effective, "DRAFT_HAS_SIDE_EFFECT")
            return ActionPolicyDecision(True, "CONTENT_DRAFT_ONLY", effective, digest)
        if effective.side_effect is ActionSideEffect.NONE:
            return self._deny(effective, "SIDE_EFFECT_UNDECLARED")
        if effective.reversibility is ActionReversibility.UNKNOWN:
            return self._deny(effective, "REVERSIBILITY_UNCLASSIFIED")
        if effective.data_sensitivity is ActionDataSensitivity.UNCLASSIFIED:
            return self._deny(effective, "DATA_SENSITIVITY_UNCLASSIFIED")
        if effective.category in _TARGET_REQUIRED and effective.target is None:
            return self._deny(effective, "ACTION_TARGET_REQUIRED")
        required_flag = _REQUIRED_FLAGS.get(effective.category)
        if required_flag is not None and required_flag not in effective.impact_flags:
            return self._deny(effective, "IMPACT_FLAG_REQUIRED")
        if (
            effective.category is ActionCategory.IRREVERSIBLE_OPERATION
            and effective.reversibility is not ActionReversibility.IRREVERSIBLE
        ):
            return self._deny(effective, "IRREVERSIBILITY_MISMATCH")
        return ActionPolicyDecision(
            True,
            "ACTION_REQUIRES_CONFIRMATION",
            effective,
            digest,
            confirmation_required=True,
        )

    # ``authorize`` is retained as a readable pure-policy alias for callers
    # that do not need the approval store.
    def authorize(
        self,
        proposal: ActionProposal,
        *,
        declared_action: ActionProposal | None = None,
    ) -> ActionPolicyDecision:
        return self.evaluate(proposal, declared_action=declared_action)

    @staticmethod
    def _apply_declared_minimum(
        proposal: ActionProposal,
        declared_action: ActionProposal | None,
    ) -> ActionProposal:
        if declared_action is None:
            return proposal
        if declared_action.category in {
            ActionCategory.NONE,
            ActionCategory.CONTENT_DRAFT,
        }:
            if proposal.is_consequential:
                raise _UndeclaredActionError("capability proposed an undeclared side effect")
            if (
                declared_action.category is ActionCategory.CONTENT_DRAFT
                and proposal.category is ActionCategory.NONE
            ):
                return declared_action
            return proposal
        # A capability's declared minimum cannot be lowered by a model or by a
        # handler result. A missing/lower proposal is evaluated as the declared
        # action, while a higher-risk proposal is evaluated on its own metadata.
        if _RISK_RANK[proposal.category] < _RISK_RANK[declared_action.category]:
            return declared_action
        return proposal

    @staticmethod
    def _deny(proposal: ActionProposal, reason: str) -> ActionPolicyDecision:
        return ActionPolicyDecision(
            False,
            reason,
            proposal,
            normalized_action_digest(proposal),
        )


class _UndeclaredActionError(InputInvalidError):
    """Internal typed signal for a capability effect absent from its contract."""


class ActionConfirmationWorkflow:
    """In-process exact, expiring, one-time action approval store."""

    def __init__(self, *, ttl_seconds: int = 300) -> None:
        if ttl_seconds <= 0:
            raise ConfigInvalidError("action confirmation TTL must be positive")
        self._ttl = ttl_seconds
        self._proposals: dict[str, ActionConfirmationProposal] = {}
        self._approvals: dict[str, ActionApproval] = {}
        self._decided: set[str] = set()
        self._by_scope: dict[tuple[str, str, str, str], str] = {}

    def propose(
        self,
        *,
        task_id: str,
        capability_id: str,
        operation: str,
        proposal: ActionProposal,
        now: datetime | None = None,
    ) -> ActionConfirmationProposal:
        stamp = _utc(now)
        digest = normalized_action_digest(proposal)
        scope = (task_id, capability_id, operation, digest)
        existing_id = self._by_scope.get(scope)
        existing = self._proposals.get(existing_id or "")
        if existing is not None and stamp < existing.expires_at:
            return existing
        confirmation_id = f"action-{secrets.token_hex(8)}"
        confirmation = ActionConfirmationProposal(
            confirmation_id=confirmation_id,
            task_id=task_id,
            capability_id=capability_id,
            operation=operation,
            proposal=proposal,
            action_digest=digest,
            created_at=stamp,
            expires_at=stamp + timedelta(seconds=self._ttl),
            nonce=secrets.token_urlsafe(12),
        )
        self._proposals[confirmation_id] = confirmation
        self._by_scope[scope] = confirmation_id
        return confirmation

    def approve(
        self,
        confirmation_id: str,
        *,
        interface: str = "api",
        now: datetime | None = None,
    ) -> ActionApproval:
        proposal = self._get_live(confirmation_id, now=now)
        if confirmation_id in self._decided:
            raise PermissionDeniedError("action confirmation already decided")
        stamp = _utc(now)
        approval = ActionApproval(
            confirmation_id=proposal.confirmation_id,
            action_digest=proposal.action_digest,
            decision="approved",
            approved_at=stamp,
            interface=interface,
        )
        self._approvals[confirmation_id] = approval
        self._decided.add(confirmation_id)
        return approval

    def deny(
        self,
        confirmation_id: str,
        *,
        interface: str = "api",
        now: datetime | None = None,
    ) -> ActionApproval:
        proposal = self._get_live(confirmation_id, now=now)
        if confirmation_id in self._decided:
            raise PermissionDeniedError("action confirmation already decided")
        stamp = _utc(now)
        approval = ActionApproval(
            confirmation_id=proposal.confirmation_id,
            action_digest=proposal.action_digest,
            decision="denied",
            approved_at=stamp,
            interface=interface,
        )
        self._approvals[confirmation_id] = approval
        self._decided.add(confirmation_id)
        return approval

    def check(
        self,
        *,
        confirmation_id: str | None,
        task_id: str,
        capability_id: str,
        operation: str,
        action_digest: str,
        now: datetime | None = None,
    ) -> bool:
        if not confirmation_id:
            return False
        proposal = self._proposals.get(confirmation_id)
        approval = self._approvals.get(confirmation_id)
        stamp = _utc(now)
        valid = bool(
            proposal
            and approval
            and approval.decision == "approved"
            and stamp < proposal.expires_at
            and proposal.task_id == task_id
            and proposal.capability_id == capability_id
            and proposal.operation == operation
            and proposal.action_digest == action_digest
            and approval.action_digest == action_digest
        )
        if valid:
            self._approvals.pop(confirmation_id, None)
        return valid

    def pending(self, *, now: datetime | None = None) -> tuple[ActionConfirmationProposal, ...]:
        stamp = _utc(now)
        return tuple(
            proposal
            for proposal in self._proposals.values()
            if proposal.confirmation_id not in self._decided and stamp < proposal.expires_at
        )

    def _get_live(
        self, confirmation_id: str, *, now: datetime | None
    ) -> ActionConfirmationProposal:
        proposal = self._proposals.get(confirmation_id)
        if proposal is None or _utc(now) >= proposal.expires_at:
            raise PermissionDeniedError("action confirmation is missing or expired")
        return proposal


class ActionAuthorizationService:
    """Combine pure action assessment with exact confirmation state."""

    def __init__(
        self,
        *,
        policy: ActionAuthorizationPolicy | None = None,
        confirmations: ActionConfirmationWorkflow | None = None,
    ) -> None:
        self.policy = policy or ActionAuthorizationPolicy()
        self.confirmations = confirmations or ActionConfirmationWorkflow()

    def assess(
        self,
        proposal: ActionProposal,
        *,
        declared_action: ActionProposal | None = None,
    ) -> ActionPolicyDecision:
        return self.policy.evaluate(proposal, declared_action=declared_action)

    def issue_confirmation(
        self,
        request: ActionAuthorizationRequest,
        assessment: ActionPolicyDecision,
    ) -> ActionConfirmationProposal:
        if not assessment.allowed or not assessment.confirmation_required:
            raise ConfigInvalidError("confirmation can only be issued for an approved risky action")
        return self.confirmations.propose(
            task_id=request.task_id,
            capability_id=request.capability_id,
            operation=request.operation,
            proposal=assessment.proposal,
            now=request.now,
        )

    def authorize(self, request: ActionAuthorizationRequest) -> ActionAuthorizationDecision:
        assessment = self.assess(
            request.proposal,
            declared_action=request.declared_action,
        )
        if not assessment.allowed:
            return ActionAuthorizationDecision(
                False,
                assessment.reason_code,
                assessment.proposal,
                assessment.action_digest,
            )
        if not assessment.confirmation_required:
            if request.confirmation_id is not None:
                return ActionAuthorizationDecision(
                    False,
                    "UNEXPECTED_CONFIRMATION",
                    assessment.proposal,
                    assessment.action_digest,
                )
            return ActionAuthorizationDecision(
                True,
                assessment.reason_code,
                assessment.proposal,
                assessment.action_digest,
            )
        if not request.confirmation_id:
            confirmation = self.issue_confirmation(request, assessment)
            return ActionAuthorizationDecision(
                False,
                "ACTION_CONFIRMATION_REQUIRED",
                assessment.proposal,
                assessment.action_digest,
                confirmation,
            )
        if self.confirmations.check(
            confirmation_id=request.confirmation_id,
            task_id=request.task_id,
            capability_id=request.capability_id,
            operation=request.operation,
            action_digest=assessment.action_digest,
            now=request.now,
        ):
            return ActionAuthorizationDecision(
                True,
                "EXACT_ACTION_CONFIRMATION_VALID",
                assessment.proposal,
                assessment.action_digest,
            )
        return ActionAuthorizationDecision(
            False,
            "ACTION_CONFIRMATION_INVALID",
            assessment.proposal,
            assessment.action_digest,
        )


def interpret_recommended_action(text: str) -> ActionProposal | None:
    """Convert legacy recommendation text into a typed model proposal.

    This is a compatibility parser, not an authorization decision.  It uses
    multi-signal semantic patterns and then sends the result through the typed
    policy.  Unknown material-effect wording is represented conservatively as
    ambiguous/unknown risk so it fails closed.
    """

    if not isinstance(text, str) or not text.strip():
        return None
    normalized = " ".join(text.split()).strip()
    lowered = normalized.casefold()

    if re.search(
        r"\b(draft|compose|prepare|write|edit|rewrite|document|documentation|report)\b",
        lowered,
    ) and not re.search(
        r"\b(transmit|send|forward|deliver|dispatch|relay|publish|delete|remove|erase|buy|purchase|pay|transfer|trade)\b",
        lowered,
    ):
        return ActionProposal(
            category=ActionCategory.CONTENT_DRAFT,
            side_effect=ActionSideEffect.NONE,
            reversibility=ActionReversibility.REVERSIBLE,
            data_sensitivity=ActionDataSensitivity.LOCAL,
            impact_flags=(
                (ActionImpactFlag.COMMUNICATION,)
                if re.search(r"\b(message|email|letter)\b", lowered)
                else ()
            ),
            source=ActionProposalSource.MODEL_PROPOSED,
        )

    if re.search(r"\b(transmit|send|forward|deliver|dispatch|relay|share)\b", lowered):
        return ActionProposal(
            category=ActionCategory.EXTERNAL_COMMUNICATION,
            target=_extract_target(normalized, kind="recipient"),
            side_effect=ActionSideEffect.EXTERNAL_STATE,
            reversibility=ActionReversibility.PARTIALLY_REVERSIBLE,
            data_sensitivity=ActionDataSensitivity.LOCAL,
            impact_flags=(ActionImpactFlag.COMMUNICATION,),
            confirmation_required=True,
            source=ActionProposalSource.MODEL_PROPOSED,
        )
    if re.search(r"\b(delete|remove|erase|purge|destroy)\b", lowered):
        return ActionProposal(
            category=ActionCategory.DELETE,
            target=_extract_target(normalized, kind="resource"),
            side_effect=ActionSideEffect.LOCAL_STATE,
            reversibility=ActionReversibility.IRREVERSIBLE,
            data_sensitivity=ActionDataSensitivity.LOCAL,
            impact_flags=(ActionImpactFlag.DELETION,),
            confirmation_required=True,
            source=ActionProposalSource.MODEL_PROPOSED,
        )
    if re.search(r"\b(buy|purchase|pay|transfer|trade|invest|place an order)\b", lowered):
        return ActionProposal(
            category=ActionCategory.FINANCIAL_TRANSACTION,
            target=_extract_target(normalized, kind="account_or_recipient"),
            side_effect=ActionSideEffect.EXTERNAL_STATE,
            reversibility=ActionReversibility.PARTIALLY_REVERSIBLE,
            data_sensitivity=ActionDataSensitivity.LOCAL,
            impact_flags=(ActionImpactFlag.FINANCIAL,),
            confirmation_required=True,
            source=ActionProposalSource.MODEL_PROPOSED,
        )
    if re.search(r"\b(change|update|reset|close|open)\b", lowered) and re.search(
        r"\b(account|password|permission|role|billing|setting)\b", lowered
    ):
        return ActionProposal(
            category=ActionCategory.ACCOUNT_CHANGE,
            target=_extract_target(normalized, kind="account"),
            side_effect=ActionSideEffect.EXTERNAL_STATE,
            reversibility=ActionReversibility.PARTIALLY_REVERSIBLE,
            data_sensitivity=ActionDataSensitivity.LOCAL,
            impact_flags=(ActionImpactFlag.ACCOUNT,),
            confirmation_required=True,
            source=ActionProposalSource.MODEL_PROPOSED,
        )
    if re.search(r"\b(overwrite|publish|save|write)\b", lowered) and re.search(
        r"\b(file|record|database|repository|site|document)\b", lowered
    ):
        return ActionProposal(
            category=ActionCategory.EXTERNAL_WRITE,
            target=_extract_target(normalized, kind="resource"),
            side_effect=ActionSideEffect.EXTERNAL_STATE,
            reversibility=ActionReversibility.PARTIALLY_REVERSIBLE,
            data_sensitivity=ActionDataSensitivity.LOCAL,
            impact_flags=(),
            confirmation_required=True,
            source=ActionProposalSource.MODEL_PROPOSED,
        )
    if re.search(r"\b(execute|run|perform|irreversible|finalize)\b", lowered):
        return ActionProposal(
            category=ActionCategory.IRREVERSIBLE_OPERATION,
            target=_extract_target(normalized, kind="operation"),
            side_effect=ActionSideEffect.EXTERNAL_STATE,
            reversibility=ActionReversibility.UNKNOWN,
            data_sensitivity=ActionDataSensitivity.UNCLASSIFIED,
            confirmation_required=True,
            source=ActionProposalSource.MODEL_PROPOSED,
        )
    return ActionProposal.none(source=ActionProposalSource.MODEL_PROPOSED)


def _extract_target(text: str, *, kind: str) -> ActionTarget | None:
    match = re.search(r"\b(?:to|for|on|from)\s+(.+)$", text, re.IGNORECASE)
    if match:
        reference = match.group(1).strip(" .,!?:;")
        if reference:
            return ActionTarget(kind=kind, reference=reference[:256])
    # Direct-object wording such as "delete the old backup" still supplies a
    # target.  Keep only the bounded object phrase, never the whole payload.
    direct = re.search(
        r"^(?:delete|remove|erase|purge|destroy|buy|purchase|pay|transfer|trade|"
        r"invest|overwrite|publish|save|write|execute|run|perform|finalize)\s+(.+)$",
        text,
        re.IGNORECASE,
    )
    if direct:
        reference = direct.group(1).strip(" .,!?:;")
        if reference:
            return ActionTarget(kind=kind, reference=reference[:256])
    return None


def _utc(value: datetime | None) -> datetime:
    stamp = value or datetime.now(timezone.utc)
    if not isinstance(stamp, datetime) or stamp.tzinfo is None:
        raise ConfigInvalidError("action timestamp must be timezone-aware")
    return stamp.astimezone(timezone.utc)

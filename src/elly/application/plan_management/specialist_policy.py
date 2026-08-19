"""Pure specialist-specific execution policy.

Generic external-boundary authorization belongs to
``CloudAuthorizationPolicy``. This module only decides whether a specialist
request fits the specialist's own manifest and resource constraints.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ...domain.errors import ConfigInvalidError
from ...specialists.contracts import SpecialistTask
from ...specialists.manifest import SpecialistManifest


@dataclass(frozen=True, slots=True)
class SpecialistPolicyRequest:
    """Typed specialist task and manifest presented to specialist policy."""

    task: SpecialistTask
    manifest: SpecialistManifest

    def __post_init__(self) -> None:
        if not isinstance(self.task, SpecialistTask):
            raise ConfigInvalidError("specialist policy task is invalid")
        if not isinstance(self.manifest, SpecialistManifest):
            raise ConfigInvalidError("specialist policy manifest is invalid")


@dataclass(frozen=True, slots=True)
class SpecialistPolicyDecision:
    """Safe specialist-only decision and the bounded provider output limit."""

    allowed: bool
    reason_code: str
    output_limit: int = 0


class SpecialistExecutionPolicy:
    """Evaluate manifest, scope, delegation, tools, and output constraints."""

    def __init__(self, *, max_output_tokens: int = 2000) -> None:
        if max_output_tokens <= 0:
            raise ConfigInvalidError("specialist max_output_tokens must be positive")
        self.max_output_tokens = max_output_tokens

    def evaluate(self, request: SpecialistPolicyRequest) -> SpecialistPolicyDecision:
        """Return a provider-free decision; no cloud or consent state is consulted."""
        if not isinstance(request, SpecialistPolicyRequest):
            raise ConfigInvalidError("specialist policy requires a typed request")

        task = request.task
        manifest = request.manifest
        if not manifest.enabled:
            return self._deny("SPECIALIST_DISABLED")
        if task.specialist_id != manifest.id:
            return self._deny("SPECIALIST_ID_MISMATCH")
        if task.delegation_depth != 1:
            return self._deny("DELEGATION_DEPTH_DENIED")
        if not task.context.strip():
            return self._deny("EMPTY_SPECIALIST_CONTEXT")
        if manifest.allowed_tools:
            return self._deny("SPECIALIST_TOOLS_DISABLED")

        scope_reason = self._scope_reason(task, manifest)
        if scope_reason is not None:
            return self._deny(scope_reason)

        return SpecialistPolicyDecision(
            allowed=True,
            reason_code="SPECIALIST_POLICY_APPROVED",
            output_limit=min(manifest.output_limit, self.max_output_tokens),
        )

    @staticmethod
    def _deny(reason_code: str) -> SpecialistPolicyDecision:
        return SpecialistPolicyDecision(False, reason_code)

    @staticmethod
    def _scope_reason(task: SpecialistTask, manifest: SpecialistManifest) -> str | None:
        """Return a stable denial code for clearly out-of-scope specialist work."""
        text = f"{task.goal} {task.context}".lower()
        prohibited = re.search(
            r"\b(medical diagnosis|diagnose|prescribe|trade stocks?|place an order|"
            r"send (?:an )?email|delete (?:a )?file|run (?:a )?(?:shell|command))\b",
            text,
        )
        if prohibited:
            return "SPECIALIST_SCOPE_PROHIBITED_OPERATION"

        # Structured operation/input validation is performed by the capability's
        # side-effect-free ``prepare`` method. The policy does not use literal
        # role markers as the sole scope gate.
        return None

"""M5 specialist authorization and execution workflow."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..domain.enums import CloudMode
from ..domain.errors import ConfigInvalidError, ConsentRequiredError, MalformedResultError, PermissionDeniedError
from ..privacy import ConsentProposal, ConsentWorkflow, PrivacyClass, classify_payload
from ..specialists.contracts import SpecialistResult, SpecialistTask, validate_result
from ..specialists.manifest import SpecialistManifest
from ..ports.specialist import SpecialistProviderPort
from ..guardrails.controller import GuardrailController


@dataclass(frozen=True, slots=True)
class SpecialistExecution:
    result: SpecialistResult
    proposal: ConsentProposal | None = None


class SpecialistWorkflow:
    """Owns privacy, consent, depth, tool, scope, and output policy."""

    def __init__(self, *, provider: SpecialistProviderPort, consent: ConsentWorkflow,
                 max_output_tokens: int = 2000, guardrails: GuardrailController | None = None,
                 provider_name: str = "openai", call_cost_usd: float = 0.0,
                 consent_max_cost_usd: float = 0.25) -> None:
        self.provider = provider
        self.consent = consent
        self.max_output_tokens = max_output_tokens
        self.guardrails = guardrails
        self.provider_name = provider_name
        self.call_cost_usd = call_cost_usd
        self.consent_max_cost_usd = consent_max_cost_usd

    def execute(self, *, task: SpecialistTask, manifest: SpecialistManifest,
                cloud_mode: CloudMode, now=None,
                request_guardrails: GuardrailController | None = None) -> SpecialistExecution:
        """Authorize and execute one depth-one specialist task or fail closed."""
        if not manifest.enabled:
            raise PermissionDeniedError("specialist is disabled")
        if task.specialist_id != manifest.id or task.delegation_depth != 1:
            raise PermissionDeniedError("specialist task is outside the authorized scope")
        self._validate_scope(task, manifest)
        if manifest.allowed_tools:
            raise PermissionDeniedError("specialist tool grants are disabled in V1")
        if task.privacy_class == PrivacyClass.UNCLASSIFIED.value:
            raise PermissionDeniedError("unclassified specialist payload fails closed")
        try:
            privacy = PrivacyClass(task.privacy_class)
        except ValueError as exc:
            raise PermissionDeniedError("invalid specialist privacy classification") from exc
        if privacy is not classify_payload(task.context):
            raise PermissionDeniedError("specialist payload classification is inconsistent")
        if privacy is PrivacyClass.RESTRICTED or manifest.privacy_class == "restricted":
            raise PermissionDeniedError("restricted content may never be sent to a cloud specialist")
        if cloud_mode is CloudMode.LOCAL_ONLY:
            raise PermissionDeniedError("cloud specialist requires cloud_permitted mode")
        proposal = None
        if privacy is PrivacyClass.LOCAL:
            purpose = f"execute {manifest.role} specialist"
            if not self.consent.check(
                proposal_id=task.approval_id, payload=task.context,
                provider=self.provider_name, model=manifest.provider_model, purpose=purpose,
                categories=(privacy.value,), max_cost=self.consent_max_cost_usd, now=now,
            ):
                proposal = self.consent.propose(
                    task_id=task.task_id, provider=self.provider_name, model=manifest.provider_model,
                    purpose=purpose, categories=(privacy.value,),
                    payload=task.context, max_cost=self.consent_max_cost_usd, now=now,
                )
                raise ConsentRequiredError("exact owner consent is required before sending local content", proposal=proposal)
        operation = lambda: self.provider.execute(
            task, model=manifest.provider_model, prompt_version=manifest.prompt_version,
            output_limit=min(manifest.output_limit, self.max_output_tokens),
        )
        try:
            if request_guardrails is None and self.guardrails is not None:
                request_guardrails = self.guardrails.for_request()
            result = request_guardrails.execute(
                operation,
                output_tokens=min(manifest.output_limit, self.max_output_tokens),
                cost_usd=self.call_cost_usd,
            ) if request_guardrails else operation()
        except ValueError as exc:
            raise MalformedResultError("specialist provider returned malformed output") from exc
        if result.recommended_action and any(word in result.recommended_action.lower() for word in ("execute", "write", "send", "delete", "trade")):
            raise PermissionDeniedError("high-impact specialist actions are disabled")
        return SpecialistExecution(result=validate_result(result))

    @staticmethod
    def _validate_scope(task: SpecialistTask, manifest: SpecialistManifest) -> None:
        """Reject clearly unrelated work before a specialist/provider call."""
        text = f"{task.goal} {task.context}".lower()
        prohibited = re.search(
            r"\b(medical diagnosis|diagnose|prescribe|trade stocks?|place an order|"
            r"send (?:an )?email|delete (?:a )?file|run (?:a )?(?:shell|command))\b",
            text,
        )
        if prohibited:
            raise PermissionDeniedError("task is outside the specialist's approved role")
        role_markers = {
            "coding": (
                "code", "function", "python", "bug", "debug", "program",
                "algorithm", "class", "method", "complexity",
            ),
            "research": (
                "research", "source", "evidence", "compare", "analyze",
                "synthesize", "current", "latest", "verify",
            ),
        }
        if not any(marker in text for marker in role_markers[manifest.role]):
            raise PermissionDeniedError("task does not match the specialist's declared role")

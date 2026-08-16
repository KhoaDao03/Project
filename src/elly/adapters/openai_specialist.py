"""OpenAI Responses Structured Outputs specialist adapter (M5/API-002)."""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from typing import Any

from ..domain.enums import (
    ActionCategory,
    ActionDataSensitivity,
    ActionImpactFlag,
    ActionProposalSource,
    ActionReversibility,
    ActionSideEffect,
    HealthState,
)
from ..domain.errors import (
    AuthenticationProviderError,
    MalformedResultError,
    ModelUnavailableError,
    PermanentProviderError,
    ProviderQuotaError,
    ProviderTimeoutError,
    RateLimitProviderError,
    TransientProviderError,
)
from ..domain.models import ActionProposal, ActionTarget, HealthReport
from ..specialists.contracts import SpecialistResult, SpecialistTask


class OpenAISpecialistProvider:
    """Normalize one tool-free OpenAI Responses call into a SpecialistResult."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        cost_per_call_usd: float = 0.0,
    ) -> None:
        self._key = (
            api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "")
        ).strip()
        self.base_url = base_url.rstrip("/")
        self.cost_per_call_usd = cost_per_call_usd
        self.last_usage: dict[str, int] = {}
        self.last_cost_usd = 0.0
        self._response_lock = threading.Lock()
        self._active_response = None

    def cancel(self) -> None:
        with self._response_lock:
            response = self._active_response
        if response is not None:
            response.close()

    def health(self) -> HealthReport:
        """Report credential configuration without probing or exposing the key."""
        state = HealthState.HEALTHY if self._key else HealthState.DISABLED
        detail = "" if self._key else "OPENAI_API_KEY not configured"
        return HealthReport(component="specialist(openai)", state=state, detail=detail)

    def execute(
        self, task: SpecialistTask, *, model: str, prompt_version: str, output_limit: int
    ) -> SpecialistResult:
        """Run one bounded, tool-free, non-stored structured specialist call."""
        if not self._key:
            raise PermanentProviderError("OpenAI specialist capability is unavailable")
        prompt = (
            f"You are specialist {task.specialist_id}. Prompt version: {prompt_version}.\n"
            "Return only JSON matching the requested schema. Do not execute tools, claim actions, or invent sources.\n"
            f"Goal: {task.goal}\nSupplied context:\n{task.context[:16000]}"
        )
        schema = {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["known", "inferred", "unknown", "blocked", "partial"],
                },
                "answer": {"type": "string"},
                "assumptions": {"type": "array", "items": {"type": "string"}},
                "uncertainties": {"type": "array", "items": {"type": "string"}},
                "key_evidence": {"type": "array", "items": {"type": "string"}},
                "sources": {"type": "array", "items": {"type": "string"}},
                "recommended_action": {"type": ["string", "null"]},
                "action_proposal": {
                    "type": ["object", "null"],
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": [item.value for item in ActionCategory],
                        },
                        "target": {
                            "type": ["object", "null"],
                            "properties": {
                                "kind": {"type": "string"},
                                "reference": {"type": "string"},
                            },
                            "required": ["kind", "reference"],
                            "additionalProperties": False,
                        },
                        "side_effect": {
                            "type": "string",
                            "enum": [item.value for item in ActionSideEffect],
                        },
                        "reversibility": {
                            "type": "string",
                            "enum": [item.value for item in ActionReversibility],
                        },
                        "data_sensitivity": {
                            "type": "string",
                            "enum": [item.value for item in ActionDataSensitivity],
                        },
                        "impact_flags": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": [item.value for item in ActionImpactFlag],
                            },
                        },
                        "confirmation_required": {"type": "boolean"},
                        "source": {
                            "type": "string",
                            "enum": [item.value for item in ActionProposalSource],
                        },
                    },
                    "required": [
                        "category",
                        "target",
                        "side_effect",
                        "reversibility",
                        "data_sensitivity",
                        "impact_flags",
                        "confirmation_required",
                        "source",
                    ],
                    "additionalProperties": False,
                },
            },
            "required": [
                "status",
                "answer",
                "assumptions",
                "uncertainties",
                "key_evidence",
                "sources",
                "recommended_action",
                "action_proposal",
            ],
            "additionalProperties": False,
        }
        body = {
            "model": model,
            "input": prompt,
            "store": False,
            "max_output_tokens": output_limit,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "specialist_result",
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        request = urllib.request.Request(
            self.base_url + "/responses",
            data=json.dumps(body).encode(),
            method="POST",
            headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                with self._response_lock:
                    self._active_response = response
                try:
                    payload = json.loads(response.read().decode("utf-8"))
                finally:
                    with self._response_lock:
                        self._active_response = None
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise AuthenticationProviderError(
                    "OpenAI specialist authentication failed"
                ) from exc
            if exc.code == 404:
                raise ModelUnavailableError(
                    "configured OpenAI specialist model is unavailable"
                ) from exc
            if exc.code == 429:
                error_code = _http_error_code(exc)
                if error_code == "insufficient_quota":
                    raise ProviderQuotaError("OpenAI specialist quota is unavailable") from exc
                raise RateLimitProviderError("OpenAI specialist rate limit reached") from exc
            if 500 <= exc.code < 600:
                raise TransientProviderError("OpenAI specialist temporarily failed") from exc
            raise PermanentProviderError("OpenAI specialist request was rejected") from exc
        except TimeoutError as exc:
            raise ProviderTimeoutError("OpenAI specialist timed out") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise ProviderTimeoutError("OpenAI specialist timed out") from exc
            raise TransientProviderError("OpenAI specialist is unavailable") from exc
        except OSError as exc:
            raise TransientProviderError("OpenAI specialist is unavailable") from exc
        usage = payload.get("usage", {})
        self.last_usage = {
            key: int(value) for key, value in usage.items() if isinstance(value, (int, float))
        }
        self.last_cost_usd = self.cost_per_call_usd
        raw = _output_text(payload)
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise TypeError("specialist output must be an object")
            if not isinstance(value.get("status"), str) or not isinstance(value.get("answer"), str):
                raise TypeError("specialist status and answer must be strings")
            for field in ("assumptions", "uncertainties", "key_evidence", "sources"):
                if not isinstance(value.get(field), list) or any(
                    not isinstance(item, str) for item in value[field]
                ):
                    raise TypeError(f"specialist {field} must be an array of strings")
            if value.get("recommended_action") is not None and not isinstance(
                value["recommended_action"], str
            ):
                raise TypeError("specialist recommended_action must be text or null")
            action_proposal = _parse_action_proposal(value.get("action_proposal"))
            result = SpecialistResult(
                status=value["status"],
                answer=value["answer"],
                assumptions=tuple(value["assumptions"]),
                uncertainties=tuple(value["uncertainties"]),
                key_evidence=tuple(value["key_evidence"]),
                sources=tuple(value["sources"]),
                recommended_action=value.get("recommended_action"),
                action_proposal=action_proposal,
                truncated=payload.get("status") == "incomplete",
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MalformedResultError(
                "OpenAI specialist returned invalid structured output"
            ) from exc
        return result


def _output_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str):
        return output_text
    for item in payload.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str):
                return text
    raise MalformedResultError("OpenAI specialist returned no structured output")


def _http_error_code(exc: urllib.error.HTTPError) -> str:
    """Read only the provider's stable error code for safe error classification."""
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        value = payload.get("error", {}).get("code", "")
        return value if isinstance(value, str) else ""
    except (AttributeError, json.JSONDecodeError, OSError, UnicodeDecodeError):
        return ""


def _parse_action_proposal(value: object) -> ActionProposal | None:
    """Strictly parse a model-proposed action object; never coerce fields."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("specialist action_proposal must be an object or null")
    target_value = value.get("target")
    target = None
    if target_value is not None:
        if not isinstance(target_value, dict):
            raise TypeError("specialist action target must be an object or null")
        if not isinstance(target_value.get("kind"), str) or not isinstance(
            target_value.get("reference"), str
        ):
            raise TypeError("specialist action target fields must be strings")
        target = ActionTarget(target_value["kind"], target_value["reference"])
    if not isinstance(value.get("impact_flags"), list) or any(
        not isinstance(item, str) for item in value["impact_flags"]
    ):
        raise TypeError("specialist action impact_flags must be an array of strings")
    if not isinstance(value.get("confirmation_required"), bool):
        raise TypeError("specialist action confirmation_required must be a bool")
    return ActionProposal(
        category=ActionCategory(value["category"]),
        target=target,
        side_effect=ActionSideEffect(value["side_effect"]),
        reversibility=ActionReversibility(value["reversibility"]),
        data_sensitivity=ActionDataSensitivity(value["data_sensitivity"]),
        impact_flags=tuple(ActionImpactFlag(item) for item in value["impact_flags"]),
        confirmation_required=value["confirmation_required"],
        source=ActionProposalSource(value["source"]),
    )

"""Local conversation use case behind the generalist application port."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain import validation
from ..domain.errors import CancelledError, EllyError, MalformedResultError
from ..domain.models import GeneralistResponse, GeneralistRequest
from ..guardrails.controller import GuardrailController
from ..ports.generalist import GeneralistPort
from .execution import CancellationToken


@dataclass(frozen=True, slots=True)
class LocalConversationExecution:
    response: GeneralistResponse
    text: str


class LocalConversationUseCase:
    """Build, execute, and validate one bounded local model request."""

    def __init__(
        self,
        *,
        generalist: GeneralistPort,
        model_id: str,
        max_output_tokens: int,
        guardrails: GuardrailController | None = None,
    ) -> None:
        self._generalist = generalist
        self._model_id = model_id
        self._max_output_tokens = max_output_tokens
        self._guardrails = guardrails

    @property
    def generalist(self) -> GeneralistPort:
        """Expose the bound port for composition/test-double replacement checks."""
        return self._generalist

    def execute(
        self,
        prompt: str,
        *,
        request_guardrails: GuardrailController | None = None,
        cancellation: CancellationToken | None = None,
    ) -> LocalConversationExecution:
        request = GeneralistRequest(
            prompt=prompt,
            model_id=self._model_id,
            max_output_tokens=self._max_output_tokens,
        )
        active_guardrails = request_guardrails
        if active_guardrails is None and self._guardrails is not None:
            active_guardrails = self._guardrails.for_request()
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        unregister = (
            cancellation.register(self._generalist.cancel)
            if cancellation is not None
            else None
        )
        try:
            if active_guardrails is None:
                response = self._generalist.generate(request)
            else:
                response = active_guardrails.execute(
                    lambda: self._generalist.generate(request),
                    cancel=self._generalist.cancel,
                    output_tokens=self._max_output_tokens,
                    cost_usd=0.0,
                )
            if cancellation is not None:
                cancellation.raise_if_cancelled()
        except EllyError as exc:
            if cancellation is not None and cancellation.cancelled:
                raise CancelledError("local generation cancelled") from exc
            raise
        finally:
            if unregister is not None:
                unregister()
        if validation.validate_generalist_text(response.text).value == "rejected":
            raise MalformedResultError("model returned empty/invalid output")
        return LocalConversationExecution(response=response, text=response.text)

"""Real localhost Ollama adapter for M2 (API-001)."""

from __future__ import annotations

import json
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..domain.enums import HealthState
from ..domain.errors import CancelledError, MalformedResultError, PermanentProviderError, ProviderTimeoutError, TransientProviderError
from ..domain.models import GeneralistRequest, GeneralistResponse, GeneralistUsage, HealthReport


class OllamaGeneralist:
    """Streaming Ollama implementation of ``GeneralistPort``.

    It accepts localhost only, never logs payloads, ignores thinking fields, and
    maps provider failures to Elly's stable error taxonomy.
    """

    def __init__(self, *, base_url: str = "http://127.0.0.1:11434", timeout_seconds: float = 120.0) -> None:
        if not base_url.startswith("http://127.0.0.1:"):
            raise ValueError("Ollama must bind to localhost")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._cancel = threading.Event()

    def health(self) -> HealthReport:
        try:
            response = urlopen(Request(self._base_url + "/api/tags", method="GET"), timeout=min(5.0, self._timeout))
            with response:
                json.load(response)
            return HealthReport(component="generalist(ollama)", state=HealthState.HEALTHY)
        except (HTTPError, URLError, OSError, TimeoutError, ValueError) as exc:
            return HealthReport(component="generalist(ollama)", state=HealthState.UNAVAILABLE, detail=type(exc).__name__)

    def cancel(self) -> None:
        self._cancel.set()

    def generate(self, request: GeneralistRequest) -> GeneralistResponse:
        if self._cancel.is_set():
            self._cancel.clear()
            raise CancelledError("local generation cancelled")
        self._cancel.clear()
        payload = json.dumps({"model": request.model_id, "prompt": request.prompt, "stream": True, "think": False, "options": {"num_predict": request.max_output_tokens}}).encode()
        started = time.monotonic()
        parts: list[str] = []
        try:
            response = urlopen(Request(self._base_url + "/api/generate", data=payload, headers={"Content-Type": "application/json"}, method="POST"), timeout=self._timeout)
            with response:
                for raw_line in response:
                    if self._cancel.is_set():
                        raise CancelledError("local generation cancelled", partial_work="".join(parts).strip())
                    try:
                        item: dict[str, Any] = json.loads(raw_line)
                    except json.JSONDecodeError as exc:
                        raise MalformedResultError("Ollama returned invalid JSON") from exc
                    if item.get("error"):
                        self._raise_provider_error(str(item["error"]))
                    value = item.get("response", "")
                    if not isinstance(value, str):
                        raise MalformedResultError("Ollama response field was not text")
                    parts.append(value)
        except CancelledError:
            raise
        except KeyboardInterrupt as exc:
            raise CancelledError("local generation cancelled", partial_work="".join(parts).strip()) from exc
        except HTTPError as exc:
            if exc.code == 404:
                raise PermanentProviderError("Ollama or configured model is unavailable") from exc
            if 500 <= exc.code < 600:
                raise TransientProviderError("Ollama returned a temporary provider error") from exc
            raise PermanentProviderError("Ollama rejected the local request") from exc
        except (URLError, ConnectionError, OSError) as exc:
            raise PermanentProviderError("Ollama is unavailable") from exc
        except TimeoutError as exc:
            raise ProviderTimeoutError("Ollama generation timed out") from exc
        text = "".join(parts).strip()
        if not text:
            raise MalformedResultError("Ollama returned empty output")
        return GeneralistResponse(text=text, usage=GeneralistUsage(output_tokens=len(text.split()), latency_ms=int((time.monotonic() - started) * 1000)))

    @staticmethod
    def _raise_provider_error(message: str) -> None:
        if "not found" in message.lower() or "pull" in message.lower():
            raise PermanentProviderError("configured Ollama model is unavailable")
        raise TransientProviderError("Ollama provider error")

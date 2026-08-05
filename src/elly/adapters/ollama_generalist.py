"""Real localhost Ollama adapter for M2 (API-001)."""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
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
        parsed = urlsplit(base_url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Ollama URL has an invalid port") from exc
        if (
            parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or port is None
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
        ):
            raise ValueError("Ollama must use an HTTP origin on 127.0.0.1")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._cancel = threading.Event()
        self._response_lock = threading.Lock()
        self._active_response = None

    def health(self) -> HealthReport:
        try:
            response = urlopen(Request(self._base_url + "/api/tags", method="GET"), timeout=min(5.0, self._timeout))
            with response:
                json.load(response)
            return HealthReport(component="generalist(ollama)", state=HealthState.HEALTHY)
        except (HTTPError, URLError, OSError, TimeoutError, ValueError) as exc:
            return HealthReport(component="generalist(ollama)", state=HealthState.UNAVAILABLE, detail=type(exc).__name__)

    def cancel(self) -> None:
        """Request cancellation and close an active HTTP response to unblock I/O."""
        self._cancel.set()
        with self._response_lock:
            response = self._active_response
        if response is not None:
            try:
                # ``HTTPResponse.close()`` alone may wait for a buffered read in
                # another thread. Shutting down the owned localhost socket first
                # makes cooperative cancellation bounded.
                sock = response.fp.raw._sock  # type: ignore[attr-defined]
                sock.shutdown(socket.SHUT_RDWR)
            except (AttributeError, OSError):
                pass
            try:
                response.close()
            except OSError:
                pass

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
            with self._response_lock:
                self._active_response = response
            try:
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
            finally:
                with self._response_lock:
                    if self._active_response is response:
                        self._active_response = None
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
        except (URLError, ConnectionError, OSError, ValueError, AttributeError) as exc:
            if self._cancel.is_set():
                raise CancelledError(
                    "local generation cancelled", partial_work="".join(parts).strip()
                ) from exc
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

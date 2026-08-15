"""OpenAI hosted ``web_search`` adapter (DEC-OQ-07, API-003)."""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from ..domain.enums import HealthState
from ..domain.errors import (
    AuthenticationProviderError,
    ModelUnavailableError,
    PermanentProviderError,
    ProviderQuotaError,
    ProviderTimeoutError,
    RateLimitProviderError,
    TransientProviderError,
)
from ..domain.models import HealthReport
from ..ports.web_research import ProviderCitation, ResearchBudget, ResearchResponse


class OpenAIHostedWebSearch:
    """Minimal stdlib Responses API adapter with ``store:false``.

    Provider-returned text and URLs are untrusted. This adapter only normalizes the
    response; application-side citation validation happens after it returns.
    """

    def __init__(
        self, *, api_key: str | None = None, model: str = "gpt-5.6-luna",
        base_url: str = "https://api.openai.com/v1", max_output_tokens: int = 2048,
    ) -> None:
        self._key = (api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "")).strip()
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.max_output_tokens = max_output_tokens
        self._response_lock = threading.Lock()
        self._active_response = None

    def cancel(self) -> None:
        with self._response_lock:
            response = self._active_response
        if response is not None:
            response.close()

    def health(self) -> HealthReport:
        """Report whether hosted search credentials are configured; make no call."""
        if not self._key:
            return HealthReport(component="research(openai_web_search)", state=HealthState.DISABLED, detail="OPENAI_API_KEY not configured")
        return HealthReport(component="research(openai_web_search)", state=HealthState.HEALTHY)

    def research(self, query: str, budget: ResearchBudget) -> ResearchResponse:
        """Run one non-stored hosted-search request and return untrusted metadata."""
        if not self._key:
            raise PermanentProviderError("hosted web research is unavailable")
        requested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        body = {
            "model": self.model,
            "input": query,
            "instructions": (
                "Use web search for this request; do not answer from model memory. "
                f"The research request time is {requested_at}. Interpret current, "
                "latest, today, and now relative to that timestamp. "
                "Give a concise current answer and attach an inline citation to every "
                "material factual claim. Prefer official, first-party, exchange, index-"
                "administrator, or established market-data sources over social media, "
                "forums, forecasts, and commentary. For a financial index or commodity "
                "quote, use a direct quote page or live financial-data feed; report the "
                "latest available level, its exact quote time or date, whether it may be "
                "delayed, and market status when available. If no timely direct quote can "
                "be sourced, say so instead of substituting an older article or forecast. "
                "Interpret S&P500, "
                "S&P 500, SP500, and SPX as the S&P 500 stock-market index. Never present "
                "a delayed quote as real-time and do not provide investment advice."
            ),
            "store": False,
            "reasoning": {"effort": "low"},
            "tools": [{
                "type": "web_search",
                "search_context_size": "medium",
                "external_web_access": True,
                "filters": {
                    "blocked_domains": [
                        "reddit.com", "quora.com", "wikipedia.org"
                    ]
                },
            }],
            "tool_choice": "required",
            "include": ["web_search_call.action.sources"],
            "max_output_tokens": self.max_output_tokens,
        }
        request = urllib.request.Request(
            self.base_url + "/responses", data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=budget.timeout_seconds) as response:
                with self._response_lock:
                    self._active_response = response
                try:
                    payload = json.loads(response.read().decode("utf-8"))
                finally:
                    with self._response_lock:
                        self._active_response = None
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise AuthenticationProviderError("hosted web research authentication failed") from exc
            if exc.code == 404:
                raise ModelUnavailableError("configured hosted research model is unavailable") from exc
            if exc.code == 429:
                if _http_error_code(exc) == "insufficient_quota":
                    raise ProviderQuotaError("hosted web research quota is unavailable") from exc
                raise RateLimitProviderError("hosted web research rate limit reached") from exc
            if 500 <= exc.code < 600:
                raise TransientProviderError("hosted web research temporarily failed") from exc
            raise PermanentProviderError("hosted web research request was rejected") from exc
        except TimeoutError as exc:
            raise ProviderTimeoutError("hosted web research timed out") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise ProviderTimeoutError("hosted web research timed out") from exc
            raise TransientProviderError("hosted web research is unavailable") from exc
        except OSError as exc:
            raise TransientProviderError("hosted web research is unavailable") from exc
        text = _response_text(payload)
        citations = _response_citations(payload)
        # A cited passage can still produce a safe answer when the provider omits
        # its top-level summary. No citations, however, can never satisfy Elly's
        # research contract and is retried by the application guardrail.
        if not citations:
            raise TransientProviderError(
                "hosted web research returned no cited sources"
            )
        return ResearchResponse(
            answer_text=text, citations=tuple(citations), provider="openai_web_search", model=self.model,
            retrieved_at=datetime.now(timezone.utc), failures=(f"latency_ms={int((time.monotonic()-started)*1000)}",),
        )


def _response_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str):
        return output_text.strip()
    parts: list[str] = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if content.get("type") in {"output_text", "text"} and isinstance(text, str):
                parts.append(text)
    return "".join(parts).strip()


def _response_citations(payload: dict[str, Any]) -> list[ProviderCitation]:
    """Extract cited spans plus consulted source metadata.

    Inline annotations may support verified claims. Search-call sources only
    establish that the provider consulted a URL, so they carry no snippet and
    can only support Elly's explicitly unverified/inferred presentation.
    """
    found: list[ProviderCitation] = []
    seen: set[str] = set()
    for item in payload.get("output", []):
        for content in item.get("content", []):
            content_text = content.get("text", "")
            annotations = content.get("annotations", [])
            for annotation in annotations:
                url = annotation.get("url") or annotation.get("ref")
                if isinstance(url, str) and url:
                    snippet = ""
                    start, end = annotation.get("start_index"), annotation.get("end_index")
                    if isinstance(content_text, str) and isinstance(start, int) and isinstance(end, int):
                        if 0 <= start < end <= len(content_text):
                            snippet = content_text[start:end].strip()
                    found.append(ProviderCitation(
                        url=url, title=str(annotation.get("title", "")),
                        publisher=str(annotation.get("publisher", "")),
                        snippet=snippet, supporting_passage=snippet,
                    ))
                    seen.add(url)
        action = item.get("action", {})
        if not isinstance(action, dict):
            continue
        for source in action.get("sources", []):
            if not isinstance(source, dict):
                continue
            url = source.get("url")
            if not isinstance(url, str) or not url or url in seen:
                continue
            found.append(ProviderCitation(
                url=url,
                title=str(source.get("title", "")),
                publisher=str(source.get("publisher", "")),
                snippet="",
            ))
            seen.add(url)
    return found


def _http_error_code(exc: urllib.error.HTTPError) -> str:
    """Read only the stable provider code; never surface the response body."""
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        value = payload.get("error", {}).get("code", "")
        return value if isinstance(value, str) else ""
    except (AttributeError, json.JSONDecodeError, OSError, UnicodeDecodeError):
        return ""

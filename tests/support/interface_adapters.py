"""Minimal in-process web/client/REST-shaped adapters for API parity tests."""

from __future__ import annotations

from elly.api.application import EllyApplication
from elly.api.contracts import (
    ApiResult,
    SourcesQuery,
    SourcesView,
    SubmitRequest,
    TaskAccepted,
    TaskView,
    TraceQuery,
    TraceView,
)


class _PublicAdapter:
    """The common transport mapping shared by the three test adapters."""

    def __init__(self, application: EllyApplication) -> None:
        self._application = application

    def submit(self, request: SubmitRequest) -> ApiResult[TaskAccepted]:
        return self._application.submit(request)

    def status(self, task_id: str) -> ApiResult[TaskView]:
        return self._application.get_task(task_id)

    def sources(self, task_id: str) -> ApiResult[SourcesView]:
        return self._application.get_sources(SourcesQuery(task_id))

    def cancel(self, task_id: str) -> ApiResult[TaskView]:
        return self._application.cancel_task(task_id)

    def trace(self, task_id: str) -> ApiResult[TraceView]:
        return self._application.get_trace(TraceQuery(task_id))


class WebTestAdapter(_PublicAdapter):
    """Web-shaped in-process adapter."""


class DesktopMobileTestAdapter(_PublicAdapter):
    """Desktop/mobile-client-shaped in-process adapter."""


class RestTestAdapter(_PublicAdapter):
    """REST-shaped in-process adapter."""

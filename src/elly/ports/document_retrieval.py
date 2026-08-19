"""Typed port for retrieving candidate source documents for evidence validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ..domain.models import EvidenceObject

if TYPE_CHECKING:
    from ..application.task_execution.cancellation import CancellationToken


@dataclass(frozen=True, slots=True)
class RetrievedDocument:
    canonical_url: str
    content: str
    retrieved_at: datetime
    content_hash: str


@runtime_checkable
class DocumentRetrievalPort(Protocol):
    def retrieve(
        self,
        evidence: EvidenceObject,
        *,
        timeout_seconds: float,
        cancellation: CancellationToken | None = None,
    ) -> RetrievedDocument:
        """Return bounded source content or raise a typed provider error."""
        ...

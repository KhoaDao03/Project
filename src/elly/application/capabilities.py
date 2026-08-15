"""Typed registry for optional executable capabilities.

Required application services are constructor dependencies.  This module is
intentionally limited to optional handlers such as research and specialists so
the registry cannot become a service locator.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ..domain.enums import Route
from ..domain.errors import ConfigInvalidError
from ..domain.models import ContextManifest, RouteRequest, TaskRequest, TaskResult
from ..privacy import ConsentProposal

if TYPE_CHECKING:
    from ..guardrails.controller import GuardrailController
    from .execution import CancellationToken


class CapabilityAvailability(str, Enum):
    """Explicit availability state visible to routing."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    """Stable, safe metadata used for registration and route proposals."""

    capability_id: str
    description: str
    routes: tuple[Route, ...]
    request_schema: str
    requires_external_boundary: bool = False
    requires_consent: bool = False
    destination: str = ""
    model: str = ""
    purpose: str = ""
    max_cost_usd: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.capability_id, str) or not self.capability_id.strip():
            raise ConfigInvalidError("capability_id must be non-empty")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ConfigInvalidError("capability description must be non-empty")
        if not isinstance(self.request_schema, str) or not self.request_schema.strip():
            raise ConfigInvalidError("capability request_schema must be non-empty")
        if not self.routes:
            raise ConfigInvalidError("capability must declare at least one route")
        if any(not isinstance(route, Route) for route in self.routes):
            raise ConfigInvalidError("capability routes must contain Route values")
        if self.max_cost_usd < 0:
            raise ConfigInvalidError("capability max_cost_usd must not be negative")


@dataclass(frozen=True, slots=True)
class CapabilityStatus:
    """Availability plus a non-sensitive diagnostic reason."""

    state: CapabilityAvailability
    reason_code: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.state, CapabilityAvailability):
            raise ConfigInvalidError("capability state must be a CapabilityAvailability")
        if not isinstance(self.reason_code, str):
            raise ConfigInvalidError("capability reason_code must be text")

    @property
    def available(self) -> bool:
        return self.state is CapabilityAvailability.AVAILABLE


@dataclass(frozen=True, slots=True)
class CapabilityMatch:
    """Result of a handler's typed request suitability check."""

    accepted: bool
    reason_code: str


@dataclass(frozen=True, slots=True)
class CapabilityRequest:
    """Common dispatch envelope; handlers keep capability-specific types inside."""

    task: TaskRequest
    route_request: RouteRequest
    context_text: str
    context_manifest: ContextManifest
    task_id: str = ""
    execution_at: datetime | None = None
    request_guardrails: "GuardrailController | None" = None
    cancellation: "CancellationToken | None" = None

    def __post_init__(self) -> None:
        if not self.context_text.strip():
            raise ConfigInvalidError("capability context_text must be non-empty")
        if not self.task_id:
            object.__setattr__(self, "task_id", f"task-{self.task.request_id}")


@dataclass(frozen=True, slots=True)
class CapabilityExecution:
    """Normalized optional-capability execution result."""

    result: TaskResult
    manifest: ContextManifest
    consent_proposal: ConsentProposal | None = None


@runtime_checkable
class CapabilityHandler(Protocol):
    """Common application contract for optional executable capabilities."""

    @property
    def descriptor(self) -> CapabilityDescriptor:
        ...

    def status(self) -> CapabilityStatus:
        ...

    def can_handle(self, request: CapabilityRequest) -> CapabilityMatch:
        ...

    def execute(self, request: CapabilityRequest) -> CapabilityExecution:
        ...


class CapabilityRegistry:
    """Composition-time registry containing optional dispatchable handlers."""

    def __init__(self, handlers: tuple[CapabilityHandler, ...] = ()) -> None:
        self._handlers: dict[str, CapabilityHandler] = {}
        for handler in handlers:
            self.register(handler)

    def register(self, handler: CapabilityHandler) -> None:
        if not isinstance(handler, CapabilityHandler):
            raise ConfigInvalidError(
                "optional registry accepts only CapabilityHandler implementations"
            )
        descriptor = handler.descriptor
        if not isinstance(descriptor, CapabilityDescriptor):
            raise ConfigInvalidError("capability descriptor has an invalid type")
        if descriptor.capability_id in self._handlers:
            raise ConfigInvalidError(
                f"duplicate capability id: {descriptor.capability_id}"
            )
        # Touch the contract during composition so malformed implementations fail
        # before an uncommon route is selected.
        status = handler.status()
        if not isinstance(status, CapabilityStatus):
            raise ConfigInvalidError(
                f"capability {descriptor.capability_id} returned invalid status"
            )
        self._handlers[descriptor.capability_id] = handler

    def get(self, capability_id: str) -> CapabilityHandler | None:
        return self._handlers.get(capability_id)

    def status(self, capability_id: str) -> CapabilityStatus:
        handler = self._handlers.get(capability_id)
        if handler is None:
            return CapabilityStatus(
                CapabilityAvailability.UNAVAILABLE,
                "CAPABILITY_NOT_REGISTERED",
            )
        return handler.status()

    def descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        return tuple(handler.descriptor for handler in self._handlers.values())

    def available(self) -> tuple[CapabilityHandler, ...]:
        return tuple(handler for handler in self._handlers.values() if handler.status().available)

    def validate(self) -> None:
        """Re-check registered contracts during application startup/health checks."""
        for handler in self._handlers.values():
            if not isinstance(handler, CapabilityHandler):
                raise ConfigInvalidError(
                    "optional registry contains a non-capability dependency"
                )
            descriptor = handler.descriptor
            if not isinstance(descriptor, CapabilityDescriptor):
                raise ConfigInvalidError(
                    "registered capability returned an invalid descriptor"
                )
            if not isinstance(handler.status(), CapabilityStatus):
                raise ConfigInvalidError(
                    f"capability {descriptor.capability_id} returned invalid status"
                )

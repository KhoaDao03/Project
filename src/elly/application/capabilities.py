"""Typed registry for optional executable capabilities.

Required application services are constructor dependencies.  This module is
intentionally limited to optional handlers such as research and specialists so
the registry cannot become a service locator.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ..domain.enums import Route
from ..domain.errors import ConfigInvalidError
from ..domain.models import (
    ActionProposal,
    CapabilityIntent,
    ContextManifest,
    RouteRequest,
    TaskRequest,
    TaskResult,
)
from ..privacy import ClassificationDecision, ConsentProposal
from .routing_contracts import (
    CandidateMatch as CandidateMatch,
)
from .routing_contracts import (
    CapabilityAvailability as CapabilityAvailability,
)
from .routing_contracts import (
    CapabilityKind as CapabilityKind,
)
from .routing_contracts import (
    CapabilityRoutingDescriptor as CapabilityRoutingDescriptor,
)
from .routing_contracts import (
    CapabilitySelectionProposal as CapabilitySelectionProposal,
)
from .routing_contracts import (
    CapabilitySelectionView as CapabilitySelectionView,
)
from .routing_contracts import (
    FreshnessRequirement as FreshnessRequirement,
)
from .routing_contracts import (
    FreshnessSupport as FreshnessSupport,
)
from .routing_contracts import (
    MatchStrength as MatchStrength,
)
from .routing_contracts import (
    OperationIntentContract as OperationIntentContract,
)
from .routing_contracts import (
    RoutingCatalog as RoutingCatalog,
)
from .routing_contracts import (
    SelectionProposal as SelectionProposal,
)
from .routing_contracts import (
    TaskIntent as TaskIntent,
)
from .routing_contracts import (
    default_routing_descriptor,
)
from .step_results import (
    RESULT_SCHEMA_VERSION,
    ActionExecutionReceipt,
    StepResultEnvelope,
)

if TYPE_CHECKING:
    from ..guardrails.controller import GuardrailController
    from .execution import CancellationToken


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    """Stable, safe metadata used for registration and route proposals."""

    capability_id: str
    description: str
    routes: tuple[Route, ...]
    request_schema: str
    operations: tuple[str, ...] = ()
    requires_external_boundary: bool = False
    requires_consent: bool = False
    destination: str = ""
    model: str = ""
    purpose: str = ""
    max_cost_usd: float = 0.0
    declared_action: ActionProposal = field(default_factory=ActionProposal.none)
    routing: CapabilityRoutingDescriptor | None = None
    output_schema_versions: tuple[str, ...] = (RESULT_SCHEMA_VERSION,)

    def __post_init__(self) -> None:
        if not isinstance(self.capability_id, str) or not self.capability_id.strip():
            raise ConfigInvalidError("capability_id must be non-empty")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ConfigInvalidError("capability description must be non-empty")
        if not isinstance(self.request_schema, str) or not self.request_schema.strip():
            raise ConfigInvalidError("capability request_schema must be non-empty")
        if not self.operations or any(
            not isinstance(operation, str) or not operation.strip() for operation in self.operations
        ):
            raise ConfigInvalidError("capability must declare at least one operation")
        if len(set(self.operations)) != len(self.operations):
            raise ConfigInvalidError("capability operations must be unique")
        if not isinstance(self.declared_action, ActionProposal):
            raise ConfigInvalidError("capability declared_action has an invalid type")
        if not isinstance(self.output_schema_versions, tuple) or not self.output_schema_versions:
            raise ConfigInvalidError("capability must declare output schema versions")
        if any(
            not isinstance(version, str) or not version.strip()
            for version in self.output_schema_versions
        ) or len(set(self.output_schema_versions)) != len(self.output_schema_versions):
            raise ConfigInvalidError("capability output schema versions are invalid")
        if self.routing is not None:
            if not isinstance(self.routing, CapabilityRoutingDescriptor):
                raise ConfigInvalidError("capability routing has an invalid type")
            if self.routing.capability_id != self.capability_id:
                raise ConfigInvalidError("capability routing ID must match capability_id")
            routing_operations = tuple(
                operation.operation_id for operation in self.routing.operations
            )
            if set(routing_operations) != set(self.operations):
                raise ConfigInvalidError(
                    "capability routing operations must match executable operations"
                )
            if any(
                operation.effect is not self.declared_action.category
                for operation in self.routing.operations
            ):
                raise ConfigInvalidError(
                    "capability routing effects must match declared action metadata"
                )
        if not self.routes:
            raise ConfigInvalidError("capability must declare at least one route")
        if any(not isinstance(route, Route) for route in self.routes):
            raise ConfigInvalidError("capability routes must contain Route values")
        if self.max_cost_usd < 0:
            raise ConfigInvalidError("capability max_cost_usd must not be negative")

    @property
    def accepted_input_types(self) -> tuple[str, ...]:
        """Return the union of application-declared operation input types."""

        if self.routing is None:
            return ("text",)
        return tuple(
            sorted(
                {
                    value
                    for operation in self.routing.operations
                    for value in operation.accepted_inputs
                }
            )
        )

    @property
    def result_schema_versions(self) -> tuple[str, ...]:
        """Compatibility alias for the descriptor's output schema versions."""

        return self.output_schema_versions


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
class CapabilityPreparation:
    """Side-effect-free validation result for one structured capability intent."""

    accepted: bool
    reason_code: str
    clarification_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.accepted, bool):
            raise ConfigInvalidError("capability preparation accepted must be a bool")
        if not isinstance(self.reason_code, str) or not self.reason_code.strip():
            raise ConfigInvalidError("capability preparation reason_code is required")
        if not isinstance(self.clarification_fields, tuple) or any(
            not isinstance(field, str) or not field.strip() for field in self.clarification_fields
        ):
            raise ConfigInvalidError("capability preparation clarification fields are invalid")


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
    operation: str = ""
    intent: CapabilityIntent | None = None
    classification: ClassificationDecision | None = None
    objective: str = ""
    plan_id: str = ""
    step_id: str = ""

    def __post_init__(self) -> None:
        if not self.context_text.strip():
            raise ConfigInvalidError("capability context_text must be non-empty")
        if not isinstance(self.operation, str):
            raise ConfigInvalidError("capability operation must be text")
        if self.intent is not None and not isinstance(self.intent, CapabilityIntent):
            raise ConfigInvalidError("capability intent has an invalid type")
        if self.classification is not None and not isinstance(
            self.classification, ClassificationDecision
        ):
            raise ConfigInvalidError("capability classification has an invalid type")
        if not self.task_id:
            object.__setattr__(self, "task_id", f"task-{self.task.request_id}")


@dataclass(frozen=True, slots=True)
class CapabilityExecution:
    """Normalized optional-capability execution result."""

    result: TaskResult
    manifest: ContextManifest
    consent_proposal: ConsentProposal | None = None
    action_proposal: ActionProposal | None = None
    result_envelope: StepResultEnvelope | None = None
    action_receipt: ActionExecutionReceipt | None = None


@runtime_checkable
class CapabilityHandler(Protocol):
    """Common application contract for optional executable capabilities."""

    @property
    def descriptor(self) -> CapabilityDescriptor: ...

    def status(self) -> CapabilityStatus: ...

    def prepare(
        self, intent: CapabilityIntent, request: CapabilityRequest
    ) -> CapabilityPreparation:
        """Validate structured operation/input without provider or state effects."""
        ...

    def propose_action(self, request: CapabilityRequest) -> ActionProposal:
        """Describe the effect this operation would create, without executing it."""
        ...

    def can_handle(self, request: CapabilityRequest) -> CapabilityMatch: ...

    def execute(self, request: CapabilityRequest) -> CapabilityExecution: ...


class CapabilityRegistry:
    """Composition-time registry containing optional dispatchable handlers."""

    def __init__(self, handlers: tuple[CapabilityHandler, ...] = ()) -> None:
        self._handlers: dict[str, CapabilityHandler] = {}
        for handler in handlers:
            self.register(handler)

    def register(self, handler: CapabilityHandler) -> None:
        if not _is_capability_handler(handler):
            raise ConfigInvalidError(
                "optional registry accepts only CapabilityHandler implementations"
            )
        descriptor = handler.descriptor
        if not isinstance(descriptor, CapabilityDescriptor):
            raise ConfigInvalidError("capability descriptor has an invalid type")
        if descriptor.capability_id in self._handlers:
            raise ConfigInvalidError(f"duplicate capability id: {descriptor.capability_id}")
        # Touch the contract during composition so malformed implementations fail
        # before an uncommon route is selected.
        status = handler.status()
        if not isinstance(status, CapabilityStatus):
            raise ConfigInvalidError(
                f"capability {descriptor.capability_id} returned invalid status"
            )
        self._handlers[descriptor.capability_id] = handler
        try:
            # Validate the routing contract at registration time as well as at
            # application startup, so malformed optional metadata cannot sit
            # dormant until a conversational request happens to inspect it.
            self.routing_catalog()
        except Exception:
            self._handlers.pop(descriptor.capability_id, None)
            raise

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

    def routing_catalog(self) -> RoutingCatalog:
        """Return an immutable, ID-sorted snapshot of routing metadata.

        The catalog contains only validated descriptive contracts. Handler
        availability is sampled at snapshot construction and no executable
        collaborator is exposed through the returned values.
        """
        entries: list[CapabilityRoutingDescriptor] = []
        for capability_id in sorted(self._handlers):
            handler = self._handlers[capability_id]
            descriptor = handler.descriptor
            status = handler.status()
            if not isinstance(status, CapabilityStatus):
                raise ConfigInvalidError(f"capability {capability_id} returned invalid status")
            routing = descriptor.routing or default_routing_descriptor(
                capability_id=descriptor.capability_id,
                description=descriptor.description,
                operations=descriptor.operations,
                availability=status.state,
                availability_reason=status.reason_code,
                effect=descriptor.declared_action.category,
                requires_external_access=descriptor.requires_external_boundary,
                requires_consent=descriptor.requires_consent,
                output_schema_versions=descriptor.output_schema_versions,
            )
            entries.append(
                replace(
                    routing,
                    availability=status.state,
                    availability_reason=status.reason_code,
                )
            )
        return tuple(entries)

    def available(self) -> tuple[CapabilityHandler, ...]:
        return tuple(handler for handler in self._handlers.values() if handler.status().available)

    def validate(self) -> None:
        """Re-check registered contracts during application startup/health checks."""
        for handler in self._handlers.values():
            if not _is_capability_handler(handler):
                raise ConfigInvalidError("optional registry contains a non-capability dependency")
            descriptor = handler.descriptor
            if not isinstance(descriptor, CapabilityDescriptor):
                raise ConfigInvalidError("registered capability returned an invalid descriptor")
            if not isinstance(handler.status(), CapabilityStatus):
                raise ConfigInvalidError(
                    f"capability {descriptor.capability_id} returned invalid status"
                )
        # Validate routing metadata at composition/startup time, not only when
        # a rarely used conversational path happens to request it.
        self.routing_catalog()


def _is_capability_handler(handler: object) -> bool:
    """Accept the Phase 4 contract while defaulting missing action metadata to read-only."""
    if isinstance(handler, CapabilityHandler):
        return True
    required = ("descriptor", "status", "prepare", "can_handle", "execute")
    return all(hasattr(handler, attribute) for attribute in required)

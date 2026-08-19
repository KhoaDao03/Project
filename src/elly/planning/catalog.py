"""Model-safe, immutable views of the live capability routing catalog."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from ..application.routing.contracts import (
    CapabilityAvailability,
    CapabilityKind,
    CapabilityRoutingDescriptor,
    OperationIntentContract,
    RoutingCatalog,
)
from ..domain.errors import InputInvalidError

CATALOG_SCHEMA_VERSION = "elly.routing-catalog.v1"


@dataclass(frozen=True, slots=True)
class PlannerOperationView:
    """Safe operation metadata exposed to a local planner."""

    operation_id: str
    description: str
    domains: tuple[str, ...]
    accepted_inputs: tuple[str, ...]
    required_entities: tuple[str, ...]
    optional_entities: tuple[str, ...]
    freshness: str
    effect: str
    specificity: int
    examples: tuple[str, ...] = ()
    counterexamples: tuple[str, ...] = ()
    output_type: str = "task_result"
    output_schema_versions: tuple[str, ...] = ()
    objective_classes: tuple[str, ...] = ()
    perspectives: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlannerCapabilityView:
    """Safe capability metadata with no handler/provider references."""

    capability_id: str
    description: str
    operations: tuple[PlannerOperationView, ...]
    available: bool
    availability_reason: str
    priority: int
    kind: str = CapabilityKind.SPECIALIST.value
    requires_external_access: bool = False
    requires_consent: bool = False


@dataclass(frozen=True, slots=True)
class PlannerCatalog:
    """Immutable catalog snapshot supplied to a planner adapter."""

    schema_version: str
    version: str
    capabilities: tuple[PlannerCapabilityView, ...]

    def __post_init__(self) -> None:
        if self.schema_version != CATALOG_SCHEMA_VERSION:
            raise InputInvalidError("unsupported planner catalog schema version")
        if not self.version.startswith("cat-"):
            raise InputInvalidError("planner catalog version is invalid")
        if not isinstance(self.capabilities, tuple):
            raise InputInvalidError("planner catalog capabilities must be immutable")
        if any(not isinstance(item, PlannerCapabilityView) for item in self.capabilities):
            raise InputInvalidError("planner catalog contains an invalid capability view")
        if any(
            not isinstance(operation, PlannerOperationView)
            for capability in self.capabilities
            for operation in capability.operations
        ):
            raise InputInvalidError("planner catalog contains an invalid operation view")
        for capability in self.capabilities:
            operation_ids = tuple(item.operation_id for item in capability.operations)
            if operation_ids != tuple(sorted(operation_ids)):
                raise InputInvalidError("planner catalog operations must be ID sorted")
            if len(set(operation_ids)) != len(operation_ids):
                raise InputInvalidError("planner catalog operation IDs must be unique")
        ids = tuple(item.capability_id for item in self.capabilities)
        if ids != tuple(sorted(ids)):
            raise InputInvalidError("planner catalog capabilities must be ID sorted")
        if len(set(ids)) != len(ids):
            raise InputInvalidError("planner catalog capability IDs must be unique")

    @property
    def capability_ids(self) -> tuple[str, ...]:
        return tuple(item.capability_id for item in self.capabilities)

    def get(self, capability_id: str) -> PlannerCapabilityView | None:
        return next(
            (item for item in self.capabilities if item.capability_id == capability_id),
            None,
        )


def _operation_view(operation: OperationIntentContract) -> PlannerOperationView:
    return PlannerOperationView(
        operation_id=operation.operation_id,
        description=operation.description,
        domains=operation.domains,
        accepted_inputs=operation.accepted_inputs,
        required_entities=operation.required_entities,
        optional_entities=operation.optional_entities,
        freshness=operation.freshness.value,
        effect=operation.effect.value,
        specificity=operation.specificity,
        examples=operation.examples,
        counterexamples=operation.counterexamples,
        output_type=operation.output_type,
        output_schema_versions=operation.output_schema_versions,
        objective_classes=operation.objective_classes,
        perspectives=operation.perspectives,
    )


def _canonical_capabilities(
    capabilities: tuple[PlannerCapabilityView, ...],
) -> list[dict[str, object]]:
    return [
        {
            "capability_id": capability.capability_id,
            "description": capability.description,
            "operations": [
                {
                    "operation_id": operation.operation_id,
                    "description": operation.description,
                    "domains": list(operation.domains),
                    "accepted_inputs": list(operation.accepted_inputs),
                    "required_entities": list(operation.required_entities),
                    "optional_entities": list(operation.optional_entities),
                    "freshness": operation.freshness,
                    "effect": operation.effect,
                    "specificity": operation.specificity,
                    "examples": list(operation.examples),
                    "counterexamples": list(operation.counterexamples),
                    "output_type": operation.output_type,
                    "output_schema_versions": list(operation.output_schema_versions),
                    "objective_classes": list(operation.objective_classes),
                    "perspectives": list(operation.perspectives),
                }
                for operation in capability.operations
            ],
            "available": capability.available,
            "availability_reason": capability.availability_reason,
            "priority": capability.priority,
            "kind": capability.kind,
            "requires_external_access": capability.requires_external_access,
            "requires_consent": capability.requires_consent,
        }
        for capability in capabilities
    ]


def build_planner_catalog(catalog: RoutingCatalog) -> PlannerCatalog:
    """Minimize a validated routing catalog for model consumption.

    The returned values contain only descriptive routing contracts.  In
    particular, no handler, provider, model, endpoint, credential, or registry
    object crosses this boundary.
    """
    if not isinstance(catalog, tuple):
        raise InputInvalidError("planner catalog source must be an immutable tuple")
    if any(not isinstance(item, CapabilityRoutingDescriptor) for item in catalog):
        raise InputInvalidError("planner catalog contains an invalid descriptor")
    views = tuple(
        PlannerCapabilityView(
            capability_id=descriptor.capability_id,
            description=descriptor.description,
            operations=tuple(
                _operation_view(item)
                for item in sorted(descriptor.operations, key=lambda item: item.operation_id)
            ),
            available=descriptor.availability is CapabilityAvailability.AVAILABLE,
            availability_reason=descriptor.availability_reason,
            priority=descriptor.priority,
            kind=descriptor.kind.value,
            requires_external_access=descriptor.requires_external_access,
            requires_consent=descriptor.requires_consent,
        )
        for descriptor in sorted(catalog, key=lambda item: item.capability_id)
    )
    canonical = json.dumps(
        _canonical_capabilities(views),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    version = "cat-" + hashlib.sha256(canonical).hexdigest()[:24]
    return PlannerCatalog(CATALOG_SCHEMA_VERSION, version, views)


def planner_catalog_to_dict(catalog: PlannerCatalog) -> dict[str, object]:
    """Serialize only the safe planner catalog fields for a model prompt."""
    if not isinstance(catalog, PlannerCatalog):
        raise InputInvalidError("planner catalog is invalid")
    return {
        "schema_version": catalog.schema_version,
        "version": catalog.version,
        "capabilities": _canonical_capabilities(catalog.capabilities),
    }


model_safe_catalog = build_planner_catalog


__all__ = [
    "CATALOG_SCHEMA_VERSION",
    "PlannerCapabilityView",
    "PlannerCatalog",
    "PlannerOperationView",
    "build_planner_catalog",
    "model_safe_catalog",
    "planner_catalog_to_dict",
]

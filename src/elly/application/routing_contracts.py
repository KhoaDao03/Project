"""Provider-free contracts for registry-driven conversational routing.

These values describe selection metadata only. They deliberately contain no
handlers, providers, repositories, policy objects, prompts, or mutable state.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import TypeAlias

from ..domain.enums import ActionCategory, IntentAmbiguity
from ..domain.errors import ConfigInvalidError, InputInvalidError
from ..domain.models import IntentEntity, IntentScalar


class CapabilityAvailability(str, Enum):
    """Whether a registered capability can be selected for execution."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class FreshnessSupport(str, Enum):
    """Freshness a capability operation can satisfy."""

    STATIC = "static"
    PREFERRED = "preferred"
    CURRENT = "current"
    LIVE = "live"


class FreshnessRequirement(str, Enum):
    """Freshness requested by a capability-neutral task intent."""

    NONE = "none"
    STATIC = "static"
    PREFERRED = "preferred"
    CURRENT = "current"
    LIVE = "live"


class MatchStrength(str, Enum):
    """Qualitative match strength retained for the generic selector phase."""

    NONE = "none"
    PARTIAL = "partial"
    PREFERRED = "preferred"
    EXACT = "exact"


SUPPORTED_INPUT_TYPES = frozenset({"text", "ticker", "context", "url", "number", "date"})
SUPPORTED_ENTITY_TYPES = frozenset(
    {
        "subject",
        "ticker",
        "company",
        "ticker_or_company",
        "person",
        "organization",
        "location",
        "security",
        "date",
    }
)

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_SAFE_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_MAX_DESCRIPTION = 500
_MAX_EXAMPLE = 240
_MAX_EXAMPLES = 8


def _config_nonempty(value: str, name: str, *, maximum: int = 64) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ConfigInvalidError(f"{name} must be a non-empty string")
    if len(value) > maximum or "\n" in value or "\r" in value:
        raise ConfigInvalidError(f"{name} exceeds its safe bound")


def _validate_identifier(value: str, name: str) -> None:
    _config_nonempty(value, name)
    if _IDENTIFIER.fullmatch(value) is None:
        raise ConfigInvalidError(f"{name} has an invalid format")


def _input_nonempty(value: str, name: str, *, maximum: int = 64) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InputInvalidError(f"{name} must be a non-empty string")
    if len(value) > maximum or "\n" in value or "\r" in value:
        raise InputInvalidError(f"{name} exceeds its safe bound")


def _validate_input_identifier(value: str, name: str) -> None:
    _input_nonempty(value, name)
    if _IDENTIFIER.fullmatch(value) is None:
        raise InputInvalidError(f"{name} has an invalid format")


def _validate_input_code(value: str, name: str) -> None:
    _input_nonempty(value, name)
    if _SAFE_CODE.fullmatch(value) is None:
        raise InputInvalidError(f"{name} has an invalid format")


def _validate_texts(
    values: tuple[str, ...],
    name: str,
    *,
    allowed: frozenset[str] | None = None,
) -> None:
    if not isinstance(values, tuple):
        raise ConfigInvalidError(f"{name} must be a tuple")
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ConfigInvalidError(f"{name} must contain non-empty strings")
    if len(set(values)) != len(values):
        raise ConfigInvalidError(f"{name} must not contain duplicates")
    if allowed is not None and not set(values) <= allowed:
        unsupported = sorted(set(values) - allowed)
        raise ConfigInvalidError(f"{name} contains unsupported values: {', '.join(unsupported)}")


def _validate_examples(values: tuple[str, ...], name: str) -> None:
    _validate_texts(values, name)
    if len(values) > _MAX_EXAMPLES or any(len(value) > _MAX_EXAMPLE for value in values):
        raise ConfigInvalidError(f"{name} exceeds its bounded example limit")


@dataclass(frozen=True, slots=True)
class OperationIntentContract:
    """Declarative scope and input contract for one capability operation."""

    operation_id: str
    description: str
    domains: tuple[str, ...]
    accepted_inputs: tuple[str, ...]
    required_entities: tuple[str, ...]
    optional_entities: tuple[str, ...] = ()
    freshness: FreshnessSupport = FreshnessSupport.STATIC
    effect: ActionCategory = ActionCategory.NONE
    specificity: int = 50
    examples: tuple[str, ...] = ()
    counterexamples: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_identifier(self.operation_id, "operation_id")
        _config_nonempty(self.description, "operation description", maximum=_MAX_DESCRIPTION)
        _validate_texts(self.domains, "operation domains")
        _validate_texts(
            self.accepted_inputs,
            "operation accepted_inputs",
            allowed=SUPPORTED_INPUT_TYPES,
        )
        if not self.accepted_inputs:
            raise ConfigInvalidError("operation must declare accepted_inputs")
        _validate_texts(
            self.required_entities,
            "operation required_entities",
            allowed=SUPPORTED_ENTITY_TYPES,
        )
        _validate_texts(
            self.optional_entities,
            "operation optional_entities",
            allowed=SUPPORTED_ENTITY_TYPES,
        )
        if set(self.required_entities) & set(self.optional_entities):
            raise ConfigInvalidError("operation required and optional entities must be disjoint")
        if not isinstance(self.freshness, FreshnessSupport):
            raise ConfigInvalidError("operation freshness must be a FreshnessSupport")
        if not isinstance(self.effect, ActionCategory):
            raise ConfigInvalidError("operation effect must be an ActionCategory")
        if isinstance(self.specificity, bool) or not 0 <= self.specificity <= 100:
            raise ConfigInvalidError("operation specificity must be between 0 and 100")
        _validate_examples(self.examples, "operation examples")
        _validate_examples(self.counterexamples, "operation counterexamples")


@dataclass(frozen=True, slots=True)
class CapabilityRoutingDescriptor:
    """Immutable, presentation-safe routing metadata for one capability."""

    capability_id: str
    description: str
    operations: tuple[OperationIntentContract, ...]
    availability: CapabilityAvailability = CapabilityAvailability.AVAILABLE
    availability_reason: str = ""
    priority: int = 50

    def __post_init__(self) -> None:
        _validate_identifier(self.capability_id, "routing capability_id")
        _config_nonempty(self.description, "routing description", maximum=_MAX_DESCRIPTION)
        if not isinstance(self.operations, tuple) or not self.operations:
            raise ConfigInvalidError("routing descriptor must declare operations")
        if any(not isinstance(operation, OperationIntentContract) for operation in self.operations):
            raise ConfigInvalidError("routing operations must contain typed contracts")
        operation_ids = tuple(operation.operation_id for operation in self.operations)
        if len(set(operation_ids)) != len(operation_ids):
            raise ConfigInvalidError("routing operation IDs must be unique per capability")
        if not isinstance(self.availability, CapabilityAvailability):
            raise ConfigInvalidError("routing availability must be a CapabilityAvailability")
        if not isinstance(self.availability_reason, str):
            raise ConfigInvalidError("routing availability_reason must be text")
        if len(self.availability_reason) > 128 or any(
            char in self.availability_reason for char in ("\n", "\r")
        ):
            raise ConfigInvalidError("routing availability_reason exceeds its safe bound")
        if self.availability_reason and _SAFE_CODE.fullmatch(self.availability_reason) is None:
            raise ConfigInvalidError("routing availability_reason must be a safe reason code")
        if isinstance(self.priority, bool) or not 0 <= self.priority <= 100:
            raise ConfigInvalidError("routing priority must be between 0 and 100")

    @property
    def available(self) -> bool:
        return self.availability is CapabilityAvailability.AVAILABLE


@dataclass(frozen=True, slots=True)
class TaskIntent:
    """Capability-neutral interpretation of a user request."""

    requested_operation: str
    domain: str
    entities: tuple[IntentEntity, ...] = ()
    arguments: Mapping[str, IntentScalar] = field(default_factory=dict)
    freshness: FreshnessRequirement = FreshnessRequirement.NONE
    expected_effect: ActionCategory = ActionCategory.NONE
    confidence: float = 0.0
    ambiguity: IntentAmbiguity = IntentAmbiguity.NONE_PROPOSED
    rationale_code: str = "INTENT_UNSPECIFIED"

    def __post_init__(self) -> None:
        _input_nonempty(self.requested_operation, "task intent requested_operation")
        _input_nonempty(self.domain, "task intent domain")
        if not isinstance(self.entities, tuple) or any(
            not isinstance(entity, IntentEntity) for entity in self.entities
        ):
            raise InputInvalidError("task intent entities must contain IntentEntity values")
        if any(entity.kind not in SUPPORTED_ENTITY_TYPES for entity in self.entities):
            raise InputInvalidError("task intent contains an unsupported entity type")
        if not isinstance(self.arguments, Mapping):
            raise InputInvalidError("task intent arguments must be a mapping")
        normalized: dict[str, IntentScalar] = {}
        for key, value in self.arguments.items():
            if not isinstance(key, str) or not key.strip():
                raise InputInvalidError("task intent argument names must be non-empty")
            if not isinstance(value, (str, int, float, bool)) and value is not None:
                raise InputInvalidError("task intent arguments must contain scalar values")
            normalized[key] = value
        object.__setattr__(self, "arguments", MappingProxyType(normalized))
        if not isinstance(self.freshness, FreshnessRequirement):
            raise InputInvalidError("task intent freshness must be a FreshnessRequirement")
        if not isinstance(self.expected_effect, ActionCategory):
            raise InputInvalidError("task intent expected_effect must be an ActionCategory")
        if isinstance(self.confidence, bool) or not 0 <= self.confidence <= 1:
            raise InputInvalidError("task intent confidence must be between 0 and 1")
        if not isinstance(self.ambiguity, IntentAmbiguity):
            raise InputInvalidError("task intent ambiguity must be an IntentAmbiguity")
        _validate_input_code(self.rationale_code, "task intent rationale_code")


@dataclass(frozen=True, slots=True)
class CandidateMatch:
    """Structured evidence for one capability-operation candidate."""

    capability_id: str
    operation_id: str
    compatible: bool
    required_inputs_satisfied: bool
    operation_match: MatchStrength
    freshness_match: MatchStrength
    domain_specificity: int
    declared_priority: int
    rejection_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_input_identifier(self.capability_id, "candidate capability_id")
        _validate_input_identifier(self.operation_id, "candidate operation_id")
        if not isinstance(self.compatible, bool) or not isinstance(
            self.required_inputs_satisfied, bool
        ):
            raise InputInvalidError("candidate boolean fields are invalid")
        if not isinstance(self.operation_match, MatchStrength):
            raise InputInvalidError("candidate operation_match is invalid")
        if not isinstance(self.freshness_match, MatchStrength):
            raise InputInvalidError("candidate freshness_match is invalid")
        if isinstance(self.domain_specificity, bool) or not 0 <= self.domain_specificity <= 100:
            raise InputInvalidError("candidate domain_specificity must be between 0 and 100")
        if isinstance(self.declared_priority, bool) or not 0 <= self.declared_priority <= 100:
            raise InputInvalidError("candidate declared_priority must be between 0 and 100")
        if not isinstance(self.rejection_codes, tuple):
            raise InputInvalidError("candidate rejection_codes must be a tuple")
        for code in self.rejection_codes:
            _validate_input_code(code, "candidate rejection code")
        if self.compatible and self.rejection_codes:
            raise InputInvalidError("compatible candidate cannot contain rejection codes")


@dataclass(frozen=True, slots=True)
class CapabilitySelectionProposal:
    """Untrusted capability selection proposal awaiting catalog validation."""

    capability_id: str
    operation_id: str
    arguments: Mapping[str, IntentScalar] = field(default_factory=dict)
    entities: tuple[IntentEntity, ...] = ()
    confidence: float = 0.0
    ambiguity: IntentAmbiguity = IntentAmbiguity.NONE_PROPOSED
    rationale_code: str = "SELECTION_UNSPECIFIED"
    ranked_alternatives: tuple[CandidateMatch, ...] = ()

    def __post_init__(self) -> None:
        _validate_input_identifier(self.capability_id, "selection capability_id")
        _validate_input_identifier(self.operation_id, "selection operation_id")
        if not isinstance(self.arguments, Mapping):
            raise InputInvalidError("selection arguments must be a mapping")
        normalized: dict[str, IntentScalar] = {}
        for key, value in self.arguments.items():
            if not isinstance(key, str) or not key.strip():
                raise InputInvalidError("selection argument names must be non-empty")
            if not isinstance(value, (str, int, float, bool)) and value is not None:
                raise InputInvalidError("selection arguments must contain scalar values")
            normalized[key] = value
        object.__setattr__(self, "arguments", MappingProxyType(normalized))
        if not isinstance(self.entities, tuple) or any(
            not isinstance(entity, IntentEntity) for entity in self.entities
        ):
            raise InputInvalidError("selection entities must contain IntentEntity values")
        if any(entity.kind not in SUPPORTED_ENTITY_TYPES for entity in self.entities):
            raise InputInvalidError("selection contains an unsupported entity type")
        if isinstance(self.confidence, bool) or not 0 <= self.confidence <= 1:
            raise InputInvalidError("selection confidence must be between 0 and 1")
        if not isinstance(self.ambiguity, IntentAmbiguity):
            raise InputInvalidError("selection ambiguity must be an IntentAmbiguity")
        _validate_input_code(self.rationale_code, "selection rationale_code")
        if not isinstance(self.ranked_alternatives, tuple) or any(
            not isinstance(candidate, CandidateMatch)
            for candidate in self.ranked_alternatives
        ):
            raise InputInvalidError("selection alternatives must contain CandidateMatch values")

    @property
    def operation(self) -> str:
        """Compatibility alias for callers that use the shorter operation name."""
        return self.operation_id


SelectionProposal = CapabilitySelectionProposal
CapabilitySelectionView = CapabilitySelectionProposal
RoutingCatalog: TypeAlias = tuple[CapabilityRoutingDescriptor, ...]


def default_routing_descriptor(
    *,
    capability_id: str,
    description: str,
    operations: tuple[str, ...],
    availability: CapabilityAvailability,
    availability_reason: str,
    effect: ActionCategory,
) -> CapabilityRoutingDescriptor:
    """Build a conservative generic contract for a programmatic capability."""
    return CapabilityRoutingDescriptor(
        capability_id=capability_id,
        description=description,
        operations=tuple(
            OperationIntentContract(
                operation_id=operation,
                description=description,
                domains=("general",),
                accepted_inputs=("text",),
                required_entities=(),
                freshness=FreshnessSupport.STATIC,
                effect=effect,
                specificity=50,
            )
            for operation in operations
        ),
        availability=availability,
        availability_reason=availability_reason,
        priority=50,
    )


__all__ = [
    "CandidateMatch",
    "CapabilityAvailability",
    "CapabilityRoutingDescriptor",
    "CapabilitySelectionProposal",
    "CapabilitySelectionView",
    "FreshnessRequirement",
    "FreshnessSupport",
    "MatchStrength",
    "OperationIntentContract",
    "RoutingCatalog",
    "SelectionProposal",
    "SUPPORTED_ENTITY_TYPES",
    "SUPPORTED_INPUT_TYPES",
    "TaskIntent",
    "default_routing_descriptor",
]

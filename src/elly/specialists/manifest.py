"""Validated specialist capability declarations (BUS-003, M5 contract foundation)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..domain.errors import ConfigInvalidError

_ID = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_RUNTIMES = {"local", "cloud"}
_RISKS = {"low", "medium", "high", "financial_guidance", "medical_guidance"}
_COSTS = {"none", "low", "medium", "high"}


@dataclass(frozen=True, slots=True)
class SpecialistManifest:
    """A declarative, non-executable specialist registration.

    The application must validate this before a future router can enable it.
    A manifest grants no tool authority and does not itself make a provider call.
    """

    id: str
    version: str
    description: str
    capabilities: frozenset[str]
    accepted_inputs: frozenset[str]
    requires_current_data: bool
    preferred_runtime: str
    risk_level: str
    estimated_cost: str
    timeout_seconds: float
    enabled: bool = True
    allowed_tools: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.id):
            raise ConfigInvalidError("specialist id must be lowercase snake_case")
        if not self.version.strip() or not self.description.strip():
            raise ConfigInvalidError(f"specialist {self.id} requires version and description")
        if not self.capabilities or any(not x.strip() for x in self.capabilities):
            raise ConfigInvalidError(f"specialist {self.id} requires capabilities")
        if not self.accepted_inputs or not self.accepted_inputs <= {"text", "ticker", "context"}:
            raise ConfigInvalidError(f"specialist {self.id} has unsupported accepted_inputs")
        if self.preferred_runtime not in _RUNTIMES:
            raise ConfigInvalidError(f"specialist {self.id} has invalid preferred_runtime")
        if self.risk_level not in _RISKS or self.estimated_cost not in _COSTS:
            raise ConfigInvalidError(f"specialist {self.id} has invalid risk or cost")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 300:
            raise ConfigInvalidError(f"specialist {self.id} timeout must be 0 < seconds <= 300")
        if any(not tool.strip() for tool in self.allowed_tools):
            raise ConfigInvalidError(f"specialist {self.id} contains an empty tool name")

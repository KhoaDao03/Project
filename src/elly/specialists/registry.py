"""Manifest discovery and registration for application-owned M5 execution."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..application.routing.contracts import FreshnessSupport, OperationIntentContract
from ..domain.enums import ActionCategory
from ..domain.errors import ConfigInvalidError
from .manifest import SpecialistManifest


@dataclass(frozen=True, slots=True)
class DisabledSpecialist:
    id: str
    reason: str


class SpecialistRegistry:
    """Registry of valid manifests and explicitly disabled invalid entries."""

    def __init__(
        self,
        *,
        default_model: str = "gpt-5.6-luna",
        model_overrides: dict[str, str] | None = None,
    ) -> None:
        self._manifests: dict[str, SpecialistManifest] = {}
        self._disabled: dict[str, DisabledSpecialist] = {}
        self._default_model = default_model
        self._model_overrides = model_overrides or {}

    @classmethod
    def from_directory(
        cls,
        directory: str,
        *,
        default_model: str,
        model_overrides: dict[str, str] | None = None,
    ) -> "SpecialistRegistry":
        """Load capability policy and inject models from the central config."""
        if not default_model.strip():
            raise ConfigInvalidError("specialist default model must be non-empty")
        registry = cls(default_model=default_model, model_overrides=model_overrides)
        path = Path(directory)
        if not path.exists():
            return registry
        if not path.is_dir():
            raise ConfigInvalidError("specialist_manifest_dir must be a directory")
        for manifest_path in sorted(path.glob("*.toml")):
            registry.load_file(manifest_path)
        return registry

    def load_file(self, path: Path) -> None:
        strict_routing_error = False
        try:
            with path.open("rb") as handle:
                raw = tomllib.load(handle)
            data: dict[str, Any] = raw.get("specialist", raw)
            if "provider_model" in data:
                raise ConfigInvalidError(
                    "provider_model belongs in the main [models] configuration"
                )
            if not isinstance(data, dict):
                raise ConfigInvalidError("specialist manifest must be a table")
            capabilities = self._string_set(data["capabilities"], "capabilities")
            accepted_inputs = self._string_set(data["accepted_inputs"], "accepted_inputs")
            allowed_tools = self._string_set(data.get("allowed_tools", []), "allowed_tools")
            exclusions = self._string_set(data.get("exclusions", []), "exclusions")
            requires_current_data = data["requires_current_data"]
            if not isinstance(requires_current_data, bool):
                raise ConfigInvalidError("requires_current_data must be boolean")
            enabled = data.get("enabled", True)
            if not isinstance(enabled, bool):
                raise ConfigInvalidError("enabled must be boolean")
            role = data.get("role", "research")
            if not isinstance(role, str):
                raise ConfigInvalidError("role must be text")
            has_routing_declaration = "routing" in raw or "routing" in data
            strict_routing_error = has_routing_declaration
            routing_data = raw.get("routing", data.get("routing", {}))
            if not isinstance(routing_data, dict):
                raise ConfigInvalidError("routing must be a table")
            if enabled and not has_routing_declaration:
                strict_routing_error = True
                raise ConfigInvalidError("enabled specialist must declare a routing contract")
            routing_priority = routing_data.get("priority", 50)
            if isinstance(routing_priority, bool) or not isinstance(routing_priority, int):
                raise ConfigInvalidError("routing priority must be an integer")
            if "legacy_route" in routing_data or "legacy_route" in data:
                raise ConfigInvalidError("legacy_route is not supported in V2.5")

            # V2.5 routing declarations are part of the executable startup
            # contract. Preserve the older quarantine behavior for malformed
            # legacy manifests, but never silently quarantine an enabled
            # manifest whose routing contract is absent or invalid.
            operations_value = routing_data.get("operations")
            if has_routing_declaration and operations_value is None:
                raise ConfigInvalidError("routing must declare operations")
            if operations_value is None:
                routing_operations: tuple[OperationIntentContract, ...] = ()
            else:
                if not isinstance(operations_value, list):
                    raise ConfigInvalidError("routing operations must be an array of tables")
                routing_operations = tuple(
                    self._routing_operation(item) for item in operations_value
                )
            manifest = SpecialistManifest(
                id=str(data["id"]),
                version=str(data["version"]),
                description=str(data["description"]),
                capabilities=capabilities,
                accepted_inputs=accepted_inputs,
                requires_current_data=requires_current_data,
                preferred_runtime=str(data["preferred_runtime"]),
                risk_level=str(data["risk_level"]),
                estimated_cost=str(data["estimated_cost"]),
                timeout_seconds=float(data["timeout_seconds"]),
                enabled=enabled,
                allowed_tools=allowed_tools,
                role=role,
                provider_model=self._model_overrides.get(str(data["id"]), self._default_model),
                prompt_version=str(data.get("prompt_version", "v1")),
                privacy_class=str(data.get("privacy_class", "remote_allowed")),
                output_limit=int(data.get("output_limit", 2000)),
                exclusions=exclusions,
                routing_priority=routing_priority,
                routing_operations=routing_operations,
            )
            if manifest.id in self._manifests:
                raise ConfigInvalidError(f"duplicate specialist id: {manifest.id}")
            self._manifests[manifest.id] = manifest
        except (
            KeyError,
            TypeError,
            ValueError,
            tomllib.TOMLDecodeError,
            OSError,
            ConfigInvalidError,
        ) as exc:
            identifier = path.stem
            self._disabled[identifier] = DisabledSpecialist(
                identifier, f"invalid manifest: {type(exc).__name__}"
            )
            if strict_routing_error:
                if isinstance(exc, ConfigInvalidError):
                    raise
                raise ConfigInvalidError(
                    f"specialist {identifier} has an invalid routing declaration"
                ) from exc

    @staticmethod
    def _string_set(value: Any, name: str) -> frozenset[str]:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ConfigInvalidError(f"specialist {name} must be an array of strings")
        return frozenset(value)

    @classmethod
    def _routing_operation(cls, value: Any) -> OperationIntentContract:
        if not isinstance(value, dict):
            raise ConfigInvalidError("routing operation must be a table")
        operation_id = value.get("id")
        description = value.get("description")
        if not isinstance(operation_id, str) or not isinstance(description, str):
            raise ConfigInvalidError("routing operation id and description must be text")
        effect = value.get("effect", ActionCategory.NONE.value)
        if effect != ActionCategory.NONE.value:
            raise ConfigInvalidError("specialist routing operations cannot declare side effects")
        freshness = value.get("freshness", FreshnessSupport.STATIC.value)
        if not isinstance(freshness, str):
            raise ConfigInvalidError("routing operation freshness must be text")
        try:
            return OperationIntentContract(
                operation_id=operation_id,
                description=description,
                domains=cls._string_tuple(value["domains"], "operation domains"),
                accepted_inputs=cls._string_tuple(
                    value["accepted_inputs"], "operation accepted_inputs"
                ),
                required_entities=cls._string_tuple(
                    value.get("required_entities", []), "operation required_entities"
                ),
                optional_entities=cls._string_tuple(
                    value.get("optional_entities", []), "operation optional_entities"
                ),
                freshness=FreshnessSupport(freshness),
                specificity=value.get("specificity", 50),
                examples=cls._string_tuple(value.get("examples", []), "operation examples"),
                counterexamples=cls._string_tuple(
                    value.get("counterexamples", []), "operation counterexamples"
                ),
            )
        except KeyError as exc:
            raise ConfigInvalidError(f"routing operation missing field: {exc.args[0]}") from exc

    @staticmethod
    def _string_tuple(value: Any, name: str) -> tuple[str, ...]:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ConfigInvalidError(f"{name} must be an array of strings")
        return tuple(value)

    def register(self, manifest: SpecialistManifest) -> None:
        if manifest.id in self._manifests:
            raise ConfigInvalidError(f"duplicate specialist id: {manifest.id}")
        self._manifests[manifest.id] = manifest

    def get(self, specialist_id: str) -> SpecialistManifest | None:
        manifest = self._manifests.get(specialist_id)
        return manifest if manifest and manifest.enabled else None

    def enabled(self) -> tuple[SpecialistManifest, ...]:
        return tuple(m for m in self._manifests.values() if m.enabled)

    def all(self) -> tuple[SpecialistManifest, ...]:
        """Return every valid manifest, including explicitly disabled ones."""
        return tuple(self._manifests.values())

    def disabled(self) -> tuple[DisabledSpecialist, ...]:
        return tuple(self._disabled.values())

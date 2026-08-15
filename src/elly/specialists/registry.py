"""Manifest discovery and registration for application-owned M5 execution."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..domain.errors import ConfigInvalidError
from .manifest import SpecialistManifest


@dataclass(frozen=True, slots=True)
class DisabledSpecialist:
    id: str
    reason: str


class SpecialistRegistry:
    """Registry of valid manifests and explicitly disabled invalid entries."""

    def __init__(
        self, *, default_model: str = "gpt-5.6-luna",
        model_overrides: dict[str, str] | None = None,
    ) -> None:
        self._manifests: dict[str, SpecialistManifest] = {}
        self._disabled: dict[str, DisabledSpecialist] = {}
        self._default_model = default_model
        self._model_overrides = model_overrides or {}

    @classmethod
    def from_directory(
        cls, directory: str, *, default_model: str,
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
        try:
            with path.open("rb") as handle:
                raw = tomllib.load(handle)
            data: dict[str, Any] = raw.get("specialist", raw)
            if "provider_model" in data:
                raise ConfigInvalidError(
                    "provider_model belongs in the main [models] configuration"
                )
            capabilities = self._string_set(data["capabilities"], "capabilities")
            accepted_inputs = self._string_set(data["accepted_inputs"], "accepted_inputs")
            allowed_tools = self._string_set(data.get("allowed_tools", []), "allowed_tools")
            exclusions = self._string_set(data.get("exclusions", []), "exclusions")
            requires_current_data = data["requires_current_data"]
            if not isinstance(requires_current_data, bool):
                raise ConfigInvalidError("requires_current_data must be boolean")
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
                enabled=bool(data.get("enabled", True)),
                allowed_tools=allowed_tools,
                role=str(data.get("role", "research")),
                provider_model=self._model_overrides.get(
                    str(data["id"]), self._default_model
                ),
                prompt_version=str(data.get("prompt_version", "v1")),
                privacy_class=str(data.get("privacy_class", "remote_allowed")),
                output_limit=int(data.get("output_limit", 2000)),
                exclusions=exclusions,
            )
            if manifest.id in self._manifests:
                raise ConfigInvalidError(f"duplicate specialist id: {manifest.id}")
            self._manifests[manifest.id] = manifest
        except (KeyError, TypeError, ValueError, tomllib.TOMLDecodeError, OSError, ConfigInvalidError) as exc:
            identifier = path.stem
            self._disabled[identifier] = DisabledSpecialist(identifier, f"invalid manifest: {type(exc).__name__}")

    @staticmethod
    def _string_set(value: Any, name: str) -> frozenset[str]:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ConfigInvalidError(f"specialist {name} must be an array of strings")
        return frozenset(value)

    def register(self, manifest: SpecialistManifest) -> None:
        if manifest.id in self._manifests:
            raise ConfigInvalidError(f"duplicate specialist id: {manifest.id}")
        self._manifests[manifest.id] = manifest

    def get(self, specialist_id: str) -> SpecialistManifest | None:
        manifest = self._manifests.get(specialist_id)
        return manifest if manifest and manifest.enabled else None

    def enabled(self) -> tuple[SpecialistManifest, ...]:
        return tuple(m for m in self._manifests.values() if m.enabled)

    def disabled(self) -> tuple[DisabledSpecialist, ...]:
        return tuple(self._disabled.values())

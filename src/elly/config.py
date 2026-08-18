"""Configuration loading and validation (OPS-002/M4).

Responsibility: assemble validated runtime settings from, in order:
  1. built-in conservative defaults (mirrors config.example.toml),
  2. an optional TOML file,
  3. ELLY_* environment overrides.
Invalid configuration fails closed with ConfigInvalidError (never a silent
default substitution for a bad value) — OPS-002 / NFR-001 intent.

OpenAI credentials are read only from the environment; missing credentials disable
hosted research without disabling local Ollama conversation (DEC-OQ-07).
"""

from __future__ import annotations

import logging
import math
import os
import re
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, NoReturn, cast
from urllib.parse import urlsplit

from .domain.errors import ConfigInvalidError

if TYPE_CHECKING:
    from .planning.contracts import PlanLimitsSnapshot

_LOCAL_MODEL_ROLES = ("conversation", "planner", "response_composer")
# Historical configuration spellings are accepted only while loading input.
# The effective Config object exposes canonical role names exclusively.
_LEGACY_LOCAL_MODEL_ROLE_ALIASES = {"synthesis": "response_composer"}
_LOCAL_MODEL_PROFILE_FIELDS = frozenset({"provider", "model_id", "base_url", "timeout_seconds"})
_PROFILE_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


def _validate_profile_name(value: object, name: str = "profile name") -> str:
    if not isinstance(value, str) or _PROFILE_NAME.fullmatch(value) is None:
        raise ConfigInvalidError(f"{name} must be a safe local-model profile identifier")
    return value


def _validate_local_endpoint(value: object, name: str = "base_url") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigInvalidError(f"{name} must be a non-empty URL")
    normalized = value.rstrip("/")
    parsed = urlsplit(normalized)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ConfigInvalidError(f"{name} has an invalid port") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigInvalidError(f"{name} must be an origin on 127.0.0.1 over HTTP")
    return normalized


@dataclass(frozen=True, slots=True)
class LocalModelProfile:
    """Reusable, validated identity for one local model endpoint."""

    name: str
    provider: str
    model_id: str
    base_url: str
    timeout_seconds: float

    def __post_init__(self) -> None:
        _validate_profile_name(self.name)
        provider = self.provider.lower() if isinstance(self.provider, str) else ""
        if provider not in {"fake", "ollama"}:
            raise ConfigInvalidError("local model provider must be fake or ollama")
        if not isinstance(self.model_id, str) or not self.model_id.strip():
            raise ConfigInvalidError("local model model_id must be non-empty")
        timeout = _as_float(
            self.timeout_seconds,
            "local model timeout_seconds",
            strictly_positive=True,
        )
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "base_url", _validate_local_endpoint(self.base_url))
        object.__setattr__(self, "timeout_seconds", timeout)


@dataclass(frozen=True, slots=True)
class LocalModelRoleConfig:
    """Immutable role binding plus an independently configurable output limit."""

    role: str
    profile: LocalModelProfile
    max_output_tokens: int

    def __post_init__(self) -> None:
        if self.role not in _LOCAL_MODEL_ROLES:
            raise ConfigInvalidError("local model role is unsupported")
        if not isinstance(self.profile, LocalModelProfile):
            raise ConfigInvalidError("local model role profile is invalid")
        if (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens <= 0
        ):
            raise ConfigInvalidError("local model role output limit must be > 0")

    @property
    def profile_name(self) -> str:
        return self.profile.name

    @property
    def provider(self) -> str:
        return self.profile.provider

    @property
    def model_id(self) -> str:
        return self.profile.model_id

    @property
    def base_url(self) -> str:
        return self.profile.base_url

    @property
    def timeout_seconds(self) -> float:
        return self.profile.timeout_seconds

    @property
    def endpoint_host(self) -> str:
        return urlsplit(self.profile.base_url).hostname or ""


@dataclass(frozen=True, slots=True)
class Config:
    """Validated runtime settings."""

    app_name: str
    db_path: str
    local_model_profiles: tuple[LocalModelProfile, ...]
    conversation_role: LocalModelRoleConfig
    planner_role: LocalModelRoleConfig
    response_composer_role: LocalModelRoleConfig
    max_input_chars: int
    context_window_messages: int
    specialist_max_output_tokens: int
    log_level: str
    specialist_manifest_dir: str
    specialist_provider: str
    specialist_default_model_id: str
    specialist_model_overrides: tuple[tuple[str, str], ...]
    max_steps: int
    max_plan_steps: int
    max_specialist_executions: int
    max_research_executions: int
    max_synthesis_executions: int
    max_replanning_attempts: int
    max_parallel_steps: int
    recursive_planning: bool
    specialist_delegation: bool
    automatic_replanning: bool
    max_provider_calls: int
    max_retries: int
    tool_timeout_seconds: float
    total_timeout_seconds: float
    max_concurrency: int
    max_queue_size: int
    monthly_budget_usd: float
    remote_call_reservation_usd: float
    consent_max_cost_usd: float
    research_provider: str
    research_model_id: str
    research_max_results: int
    research_max_output_tokens: int
    research_timeout_seconds: float
    session_retention_days: int
    evidence_retention_days: int
    audit_retention_days: int
    backup_dir: str

    def __post_init__(self) -> None:
        if not self.local_model_profiles:
            raise ConfigInvalidError("at least one local model profile is required")
        names = tuple(profile.name for profile in self.local_model_profiles)
        if len(set(names)) != len(names):
            raise ConfigInvalidError("local model profile names must be unique")
        roles = (self.conversation_role, self.planner_role, self.response_composer_role)
        if tuple(role.role for role in roles) != _LOCAL_MODEL_ROLES:
            raise ConfigInvalidError(
                "local model roles must be conversation, planner, response_composer"
            )
        for role in roles:
            if role.profile_name not in names:
                raise ConfigInvalidError(
                    f"local model role {role.role} references an unknown profile"
                )

    def specialist_model_id(self, specialist_id: str) -> str:
        """Resolve a specialist model from this one centralized configuration."""
        return dict(self.specialist_model_overrides).get(
            specialist_id, self.specialist_default_model_id
        )

    def local_model_profile(self, name: str) -> LocalModelProfile:
        """Return one immutable named local-model profile."""
        for profile in self.local_model_profiles:
            if profile.name == name:
                return profile
        raise ConfigInvalidError(f"unknown local model profile: {name}")

    def local_model_role(self, role: str) -> LocalModelRoleConfig:
        """Return the resolved immutable configuration for one logical role."""
        roles = {
            "conversation": self.conversation_role,
            "planner": self.planner_role,
            "response_composer": self.response_composer_role,
        }
        try:
            return roles[role]
        except KeyError as exc:
            raise ConfigInvalidError(f"unknown local model role: {role}") from exc

    def execution_plan_limits(self) -> PlanLimitsSnapshot:
        """Return the immutable V3 ceilings captured by a validated plan."""
        from .planning.contracts import PlanLimitsSnapshot

        return PlanLimitsSnapshot(
            max_plan_steps=self.max_plan_steps,
            max_specialist_executions=self.max_specialist_executions,
            max_research_executions=self.max_research_executions,
            max_synthesis_executions=self.max_synthesis_executions,
            max_provider_calls=self.max_provider_calls,
            max_concurrency=self.max_concurrency,
            max_replanning_attempts=(
                self.max_replanning_attempts if self.automatic_replanning else 0
            ),
            max_parallel_steps=self.max_parallel_steps,
            max_step_timeout_seconds=self.tool_timeout_seconds,
            max_total_timeout_seconds=self.total_timeout_seconds,
        )

_DEFAULTS: dict[str, object] = {
    "app_name": "elly",
    "db_path": "data/elly.db",
    "max_input_chars": 20000,
    "context_window_messages": 20,
    "specialist_max_output_tokens": 2000,
    "log_level": "INFO",
    "specialist_manifest_dir": "config/specialists",
    "specialist_provider": "openai",
    "specialist_default_model_id": "gpt-5.6-luna",
    "specialist_model_overrides": (),
    "max_steps": 6,
    "max_plan_steps": 5,
    "max_specialist_executions": 2,
    "max_research_executions": 1,
    "max_synthesis_executions": 1,
    "max_replanning_attempts": 1,
    "max_parallel_steps": 2,
    "recursive_planning": False,
    "specialist_delegation": False,
    "automatic_replanning": True,
    "max_provider_calls": 3,
    "max_retries": 1,
    "tool_timeout_seconds": 60.0,
    # Supports the bounded research -> specialist -> finalization path at the
    # default 60-second per-step ceiling.
    "total_timeout_seconds": 180.0,
    "max_concurrency": 2,
    "max_queue_size": 1,
    "monthly_budget_usd": 10.0,
    # Conservative remote-call reservation derived from the approved token
    # rates; local Ollama calls are not routed through this ledger.
    "remote_call_reservation_usd": 0.01,
    "consent_max_cost_usd": 0.25,
    "research_provider": "openai_web_search",
    "research_model_id": "gpt-5.6-luna",
    "research_max_results": 5,
    "research_max_output_tokens": 2048,
    "research_timeout_seconds": 60.0,
    "session_retention_days": 30,
    "evidence_retention_days": 7,
    "audit_retention_days": 90,
    "backup_dir": "data/backups",
}

_DEFAULT_LOCAL_PROFILE: dict[str, object] = {
    "provider": "ollama",
    "model_id": "qwen3:8b",
    "base_url": "http://127.0.0.1:11434",
    "timeout_seconds": 120.0,
}
_DEFAULT_LOCAL_ROLE_LIMITS: dict[str, int] = {
    "conversation": 512,
    "planner": 1200,
    "response_composer": 1600,
}


def _as_positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, bytes, bytearray, int, float)):
        raise ConfigInvalidError(f"{name} must be an integer")
    try:
        ivalue = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigInvalidError(f"{name} must be an integer") from exc
    if ivalue <= 0:
        raise ConfigInvalidError(f"{name} must be > 0")
    return ivalue


def _as_nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, bytes, bytearray, int, float)):
        raise ConfigInvalidError(f"{name} must be an integer")
    try:
        ivalue = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigInvalidError(f"{name} must be an integer") from exc
    if ivalue < 0:
        raise ConfigInvalidError(f"{name} must be >= 0")
    return ivalue


def _as_bool(value: object, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ConfigInvalidError(f"{name} must be a boolean")


def _as_float(
    value: object,
    name: str,
    *,
    minimum: float = 0.0,
    strictly_positive: bool = False,
) -> float:
    try:
        fvalue = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigInvalidError(f"{name} must be a number") from exc
    if not math.isfinite(fvalue):
        raise ConfigInvalidError(f"{name} must be finite")
    if strictly_positive and fvalue <= minimum:
        raise ConfigInvalidError(f"{name} must be > {minimum}")
    if not strictly_positive and fvalue < minimum:
        raise ConfigInvalidError(f"{name} must be >= {minimum}")
    return fvalue


def _from_toml(path: str) -> dict[str, object]:
    try:
        with open(path, "rb") as handle:
            raw = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ConfigInvalidError(f"config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigInvalidError(f"config file is not valid TOML: {path}") from exc

    flat: dict[str, object] = {}
    app = raw.get("app", {})
    limits = raw.get("limits", {})
    orchestration = raw.get("orchestration", {})
    generalist = raw.get("generalist", {})
    log = raw.get("log", {})
    # Central operational selection. These tables are authoritative when both
    # they and a legacy capability-local key are present.
    providers = raw.get("providers", {})
    models = raw.get("models", {})
    pricing = raw.get("pricing", {})
    research = raw.get("research", {})
    storage = raw.get("storage", {})
    specialists = raw.get("specialists", {})
    for name, value in (
        ("app", app),
        ("limits", limits),
        ("orchestration", orchestration),
        ("generalist", generalist),
        ("log", log),
        ("providers", providers),
        ("models", models),
        ("pricing", pricing),
        ("research", research),
        ("storage", storage),
        ("specialists", specialists),
    ):
        if not isinstance(value, dict):
            raise ConfigInvalidError(f"{name} must be a TOML table")
    local_models = raw.get("local_models")
    if local_models is not None:
        if not isinstance(local_models, dict):
            raise ConfigInvalidError("local_models must be a TOML table")
        flat["_local_models_declared"] = True
        profiles = local_models.get("profiles", {})
        if not isinstance(profiles, dict):
            raise ConfigInvalidError("local_models.profiles must be a TOML table")
        profile_entries = tuple(
            (str(name), dict(values))
            for name, values in profiles.items()
            if isinstance(values, dict)
        )
        if len(profile_entries) != len(profiles):
            raise ConfigInvalidError("local model profiles must be TOML tables")
        flat["_local_model_profiles"] = profile_entries
        roles = local_models.get("roles", {})
        if not isinstance(roles, dict):
            raise ConfigInvalidError("local_models.roles must be a TOML table")
        flat["_local_model_roles"] = tuple((str(role), value) for role, value in roles.items())
        role_limits = local_models.get("role_limits", {})
        if not isinstance(role_limits, dict):
            raise ConfigInvalidError("local_models.role_limits must be a TOML table")
        flat["_local_model_role_limits"] = tuple(
            (str(role_limit), value) for role_limit, value in role_limits.items()
        )
    if "name" in app:
        flat["app_name"] = app["name"]
    if "db_path" in app:
        flat["db_path"] = app["db_path"]
    if "max_input_chars" in limits:
        flat["max_input_chars"] = limits["max_input_chars"]
    if "context_window_messages" in limits:
        flat["context_window_messages"] = limits["context_window_messages"]
    if "specialist_max_output_tokens" in limits:
        flat["specialist_max_output_tokens"] = limits["specialist_max_output_tokens"]
    for key in (
        "max_steps",
        "max_provider_calls",
        "max_retries",
        "max_concurrency",
        "max_queue_size",
    ):
        if key in limits:
            flat[key] = limits[key]
    for key in (
        "max_plan_steps",
        "max_specialist_executions",
        "max_research_executions",
        "max_synthesis_executions",
        "max_replans",
        "max_parallel_steps",
        "recursive_planning",
        "specialist_delegation",
        "automatic_replanning",
    ):
        if key in orchestration:
            flat["max_replanning_attempts" if key == "max_replans" else key] = orchestration[key]
    legacy_local_profile: dict[str, object] = {}
    for key in (
        "tool_timeout_seconds",
        "total_timeout_seconds",
        "monthly_budget_usd",
        "provider_call_cost_usd",
    ):
        if key in limits:
            destination = "remote_call_reservation_usd" if key == "provider_call_cost_usd" else key
            flat[destination] = limits[key]
            if key == "provider_call_cost_usd":
                flat["_legacy_pricing_configured"] = True
    for key in ("provider", "model_id", "max_results", "max_output_tokens", "timeout_seconds"):
        if key in research:
            flat[
                {
                    "provider": "research_provider",
                    "model_id": "research_model_id",
                    "max_results": "research_max_results",
                    "max_output_tokens": "research_max_output_tokens",
                    "timeout_seconds": "research_timeout_seconds",
                }[key]
            ] = research[key]
    for key in ("session_retention_days", "evidence_retention_days", "audit_retention_days"):
        if key in storage:
            flat[key] = storage[key]
    if "backup_dir" in storage:
        flat["backup_dir"] = storage["backup_dir"]
    for key in ("model_id", "provider", "max_output_tokens", "base_url", "timeout_seconds"):
        if key in generalist:
            legacy_local_profile[key] = generalist[key]
    if "manifest_dir" in specialists:
        flat["specialist_manifest_dir"] = specialists["manifest_dir"]
    # New centralized tables override the legacy [generalist], [research], and
    # [limits] locations above, giving operators exactly one edit surface.
    for name, destination in (
        ("generalist", "provider"),
        ("research", "research_provider"),
        ("specialists", "specialist_provider"),
    ):
        if name in providers:
            if name == "generalist":
                legacy_local_profile[destination] = providers[name]
            else:
                flat[destination] = providers[name]
    for name, destination in (
        ("generalist", "model_id"),
        ("research", "research_model_id"),
        ("specialist_default", "specialist_default_model_id"),
    ):
        if name in models:
            if name == "generalist":
                legacy_local_profile[destination] = models[name]
            else:
                flat[destination] = models[name]
    specialist_models = models.get("specialists", {})
    if specialist_models:
        if not isinstance(specialist_models, dict):
            raise ConfigInvalidError("models.specialists must be a TOML table")
        flat["specialist_model_overrides"] = tuple(
            (str(key), str(value)) for key, value in specialist_models.items()
        )
    for name, destination in (
        ("monthly_budget_usd", "monthly_budget_usd"),
        ("remote_call_reservation_usd", "remote_call_reservation_usd"),
        ("consent_max_cost_usd", "consent_max_cost_usd"),
    ):
        if name in pricing:
            if name == "remote_call_reservation_usd" and flat.get(
                "_legacy_pricing_configured", False
            ):
                raise ConfigInvalidError(
                    "configure only remote_call_reservation_usd or its deprecated "
                    "provider_call_cost_usd alias"
                )
            flat[destination] = pricing[name]
    if "level" in log:
        flat["log_level"] = log["level"]
    legacy_generalist_configured = bool(
        "generalist" in raw
        or "generalist" in providers
        or "generalist" in models
    )
    flat["_legacy_generalist_configured"] = legacy_generalist_configured
    if legacy_local_profile:
        flat["_legacy_local_profile"] = legacy_local_profile
    if any(
        role == "synthesis"
        for role, _value in _pairs(flat.get("_local_model_roles"), "local_models.roles")
    ) or any(
        key == "synthesis_max_output_tokens"
        for key, _value in _pairs(
            flat.get("_local_model_role_limits"), "local_models.role_limits"
        )
    ):
        flat["_legacy_role_alias_configured"] = True
    return flat


def _from_env() -> dict[str, object]:
    env_map = {
        "ELLY_DB_PATH": "db_path",
        "ELLY_MAX_INPUT_CHARS": "max_input_chars",
        "ELLY_CONTEXT_WINDOW_MESSAGES": "context_window_messages",
        "ELLY_SPECIALIST_MAX_OUTPUT_TOKENS": "specialist_max_output_tokens",
        "ELLY_LOG_LEVEL": "log_level",
        "ELLY_SPECIALIST_MANIFEST_DIR": "specialist_manifest_dir",
        "ELLY_SPECIALIST_PROVIDER": "specialist_provider",
        "ELLY_SPECIALIST_DEFAULT_MODEL_ID": "specialist_default_model_id",
        "ELLY_MAX_STEPS": "max_steps",
        "ELLY_MAX_PLAN_STEPS": "max_plan_steps",
        "ELLY_MAX_SPECIALIST_EXECUTIONS": "max_specialist_executions",
        "ELLY_MAX_RESEARCH_EXECUTIONS": "max_research_executions",
        "ELLY_MAX_SYNTHESIS_EXECUTIONS": "max_synthesis_executions",
        "ELLY_MAX_REPLANS": "max_replanning_attempts",
        "ELLY_MAX_PARALLEL_STEPS": "max_parallel_steps",
        "ELLY_RECURSIVE_PLANNING": "recursive_planning",
        "ELLY_SPECIALIST_DELEGATION": "specialist_delegation",
        "ELLY_AUTOMATIC_REPLANNING": "automatic_replanning",
        "ELLY_MAX_PROVIDER_CALLS": "max_provider_calls",
        "ELLY_MAX_RETRIES": "max_retries",
        "ELLY_TOOL_TIMEOUT_SECONDS": "tool_timeout_seconds",
        "ELLY_TOTAL_TIMEOUT_SECONDS": "total_timeout_seconds",
        "ELLY_MAX_CONCURRENCY": "max_concurrency",
        "ELLY_MAX_QUEUE_SIZE": "max_queue_size",
        "ELLY_MONTHLY_BUDGET_USD": "monthly_budget_usd",
        "ELLY_REMOTE_CALL_RESERVATION_USD": "remote_call_reservation_usd",
        "ELLY_CONSENT_MAX_COST_USD": "consent_max_cost_usd",
        "ELLY_RESEARCH_PROVIDER": "research_provider",
        "ELLY_RESEARCH_MODEL_ID": "research_model_id",
        "ELLY_RESEARCH_MAX_RESULTS": "research_max_results",
        "ELLY_RESEARCH_MAX_OUTPUT_TOKENS": "research_max_output_tokens",
        "ELLY_RESEARCH_TIMEOUT_SECONDS": "research_timeout_seconds",
        "ELLY_SESSION_RETENTION_DAYS": "session_retention_days",
        "ELLY_EVIDENCE_RETENTION_DAYS": "evidence_retention_days",
        "ELLY_AUDIT_RETENTION_DAYS": "audit_retention_days",
        "ELLY_BACKUP_DIR": "backup_dir",
    }
    out: dict[str, object] = {}
    for env_name, key in env_map.items():
        if env_name in os.environ:
            out[key] = os.environ[env_name]
    legacy_profile: dict[str, object] = {}
    for env_name, field_name in (
        ("ELLY_GENERALIST_MODEL_ID", "model_id"),
        ("ELLY_GENERALIST_PROVIDER", "provider"),
        ("ELLY_GENERALIST_MAX_OUTPUT_TOKENS", "max_output_tokens"),
        ("ELLY_OLLAMA_BASE_URL", "base_url"),
        ("ELLY_OLLAMA_TIMEOUT_SECONDS", "timeout_seconds"),
    ):
        if env_name in os.environ:
            legacy_profile[field_name] = os.environ[env_name]
    if legacy_profile:
        out["_legacy_local_profile"] = legacy_profile
    legacy_names = {
        "ELLY_GENERALIST_MODEL_ID",
        "ELLY_GENERALIST_PROVIDER",
        "ELLY_GENERALIST_MAX_OUTPUT_TOKENS",
        "ELLY_OLLAMA_BASE_URL",
        "ELLY_OLLAMA_TIMEOUT_SECONDS",
    }
    out["_legacy_generalist_configured"] = bool(legacy_names.intersection(os.environ))
    if "ELLY_PROVIDER_CALL_COST_USD" in os.environ:
        if "ELLY_REMOTE_CALL_RESERVATION_USD" in os.environ:
            raise ConfigInvalidError(
                "configure only ELLY_REMOTE_CALL_RESERVATION_USD or its deprecated "
                "ELLY_PROVIDER_CALL_COST_USD alias"
            )
        out["remote_call_reservation_usd"] = os.environ["ELLY_PROVIDER_CALL_COST_USD"]
        out["_legacy_pricing_configured"] = True

    role_bindings: list[tuple[str, object]] = []
    role_limits: list[tuple[str, object]] = []
    # ``synthesis`` is retained only as an explicit migration alias at this
    # input boundary.  Effective configuration exposes response_composer.
    env_roles = _LOCAL_MODEL_ROLES + ("synthesis",)
    for role in env_roles:
        upper_role = role.upper()
        binding_names = (
            f"ELLY_LOCAL_{upper_role}_PROFILE",
            f"ELLY_LOCAL_MODELS_{upper_role}_PROFILE",
        )
        binding_values = [os.environ[name] for name in binding_names if name in os.environ]
        if len(set(binding_values)) > 1:
            raise ConfigInvalidError(
                f"conflicting environment bindings for local model role {role}"
            )
        if binding_values:
            role_bindings.append((role, binding_values[0]))

        limit_names = (
            f"ELLY_LOCAL_{upper_role}_MAX_OUTPUT_TOKENS",
            f"ELLY_LOCAL_MODELS_{upper_role}_MAX_OUTPUT_TOKENS",
        )
        limit_values = [os.environ[name] for name in limit_names if name in os.environ]
        if len(set(limit_values)) > 1:
            raise ConfigInvalidError(
                f"conflicting environment output limits for local model role {role}"
            )
        if limit_values:
            role_limits.append((role, limit_values[0]))
    if role_bindings:
        out["_local_model_role_env"] = tuple(role_bindings)
    if role_limits:
        out["_local_model_role_limit_env"] = tuple(role_limits)
    if any(role == "synthesis" for role, _value in role_bindings) or any(
        key.startswith("synthesis") for key, _value in role_limits
    ):
        out["_legacy_role_alias_configured"] = True

    profile_env: dict[str, dict[str, object]] = {}
    profile_fields = {
        "PROVIDER": "provider",
        "MODEL_ID": "model_id",
        "BASE_URL": "base_url",
        "TIMEOUT_SECONDS": "timeout_seconds",
    }
    for env_name, value in os.environ.items():
        prefix = "ELLY_LOCAL_MODELS_"
        if not env_name.startswith(prefix):
            continue
        for suffix, field_name in profile_fields.items():
            marker = f"_{suffix}"
            if not env_name.endswith(marker):
                continue
            encoded_name = env_name[len(prefix) : -len(marker)]
            if not encoded_name:
                continue
            profile_name = encoded_name.lower()
            profile_env.setdefault(profile_name, {})[field_name] = value
            break
    if profile_env:
        out["_local_model_profile_env"] = tuple(
            (name, dict(fields)) for name, fields in profile_env.items()
        )
    return out


def _pairs(value: object, name: str) -> tuple[tuple[str, object], ...]:
    if value is None:
        return ()
    if not isinstance(value, tuple):
        raise ConfigInvalidError(f"{name} must be a table")
    result: list[tuple[str, object]] = []
    for item in value:
        if not isinstance(item, tuple) or len(item) != 2 or not isinstance(item[0], str):
            raise ConfigInvalidError(f"{name} contains an invalid entry")
        result.append((item[0], item[1]))
    return tuple(result)


def _local_profile_values(value: object, name: str) -> tuple[tuple[str, dict[str, object]], ...]:
    entries = _pairs(value, name)
    result: list[tuple[str, dict[str, object]]] = []
    for profile_name, raw_fields in entries:
        if not isinstance(raw_fields, dict):
            raise ConfigInvalidError(f"{name} profile {profile_name} must be a table")
        result.append((profile_name, dict(raw_fields)))
    return tuple(result)


def _apply_profile_overrides(
    profiles: dict[str, dict[str, object]],
    overrides: tuple[tuple[str, dict[str, object]], ...],
    *,
    source: str,
) -> None:
    for profile_name, fields in overrides:
        _validate_profile_name(profile_name, f"{source} profile name")
        target = profiles.setdefault(profile_name, {})
        unknown = set(fields) - _LOCAL_MODEL_PROFILE_FIELDS
        if unknown:
            raise ConfigInvalidError(
                f"{source} profile {profile_name} has unsupported fields: "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        target.update(fields)


def _apply_role_bindings(
    bindings: dict[str, str], entries: tuple[tuple[str, object], ...], source: str
) -> None:
    for role, profile_name in entries:
        canonical_role = _LEGACY_LOCAL_MODEL_ROLE_ALIASES.get(role, role)
        if canonical_role not in _LOCAL_MODEL_ROLES:
            raise ConfigInvalidError(f"{source} contains an unsupported local model role: {role}")
        if not isinstance(profile_name, str) or not profile_name.strip():
            raise ConfigInvalidError(f"{source} binding for {role} must name a profile")
        bindings[canonical_role] = profile_name


def _apply_role_limits(
    limits: dict[str, object], entries: tuple[tuple[str, object], ...], source: str
) -> None:
    for key, value in entries:
        role = key.removesuffix("_max_output_tokens")
        role = _LEGACY_LOCAL_MODEL_ROLE_ALIASES.get(role, role)
        if role not in _LOCAL_MODEL_ROLES:
            raise ConfigInvalidError(f"{source} contains an unsupported role limit: {key}")
        limits[role] = value


def _reject_role_alias_conflicts(
    *entry_sets: object,
) -> None:
    """Reject simultaneous legacy and canonical composer bindings.

    The default binding is not considered an explicit binding.  This lets an
    old configuration containing only ``synthesis`` migrate safely, while a
    file/environment pair that names both forms fails closed instead of
    silently selecting one.
    """

    seen: dict[str, set[str]] = {}
    for entries in entry_sets:
        for role, _value in _pairs(entries, "local model role entries"):
            canonical = _LEGACY_LOCAL_MODEL_ROLE_ALIASES.get(role, role)
            spellings = seen.setdefault(canonical, set())
            if spellings and role not in spellings:
                raise ConfigInvalidError(
                    "conflicting local model role bindings for response_composer: "
                    "configure only response_composer or its deprecated synthesis alias"
                )
            # The same spelling may be layered by environment over TOML using
            # the normal configuration precedence rules.  Only mixed legacy
            # and canonical spellings are unsafe and rejected above.
            spellings.add(role)


def _reject_role_limit_alias_conflicts(
    *entry_sets: object,
) -> None:
    """Apply the same explicit conflict rule to role output-limit aliases."""

    seen: dict[str, set[str]] = {}
    for entries in entry_sets:
        for key, _value in _pairs(entries, "local model role limit entries"):
            role = key.removesuffix("_max_output_tokens")
            canonical = _LEGACY_LOCAL_MODEL_ROLE_ALIASES.get(role, role)
            spellings = seen.setdefault(canonical, set())
            if spellings and role not in spellings:
                raise ConfigInvalidError(
                    "conflicting local model role limits for response_composer: "
                    "configure only response_composer or its deprecated synthesis alias"
                )
            spellings.add(role)


def _build_local_roles(
    merged: dict[str, object],
    toml_values: dict[str, object],
    env_values: dict[str, object],
) -> tuple[tuple[LocalModelProfile, ...], tuple[LocalModelRoleConfig, ...]]:
    legacy = bool(toml_values.get("_legacy_generalist_configured")) or bool(
        env_values.get("_legacy_generalist_configured")
    )
    new_configuration = bool(toml_values.get("_local_models_declared")) or any(
        key in env_values
        for key in (
            "_local_model_role_env",
            "_local_model_role_limit_env",
            "_local_model_profile_env",
        )
    )

    if legacy and not new_configuration:
        legacy_profile: dict[str, object] = dict(_DEFAULT_LOCAL_PROFILE)
        for values in (
            toml_values.get("_legacy_local_profile"),
            env_values.get("_legacy_local_profile"),
        ):
            if values is not None and not isinstance(values, dict):
                raise ConfigInvalidError("legacy local-model configuration is invalid")
            if isinstance(values, dict):
                legacy_profile.update(values)
        profiles: dict[str, dict[str, object]] = {
            "v2_generalist": {
                "provider": legacy_profile["provider"],
                "model_id": legacy_profile["model_id"],
                "base_url": legacy_profile["base_url"],
                "timeout_seconds": legacy_profile["timeout_seconds"],
            }
        }
        role_bindings = {role: "v2_generalist" for role in _LOCAL_MODEL_ROLES}
    else:
        profiles = {"qwen_default": dict(_DEFAULT_LOCAL_PROFILE)}
        _apply_profile_overrides(
            profiles,
            _local_profile_values(
                toml_values.get("_local_model_profiles"),
                "local_models.profiles",
            ),
            source="local_models.profiles",
        )
        role_bindings = {role: "qwen_default" for role in _LOCAL_MODEL_ROLES}

    env_profile_overrides = _local_profile_values(
        env_values.get("_local_model_profile_env"),
        "local model environment profiles",
    )
    _apply_profile_overrides(profiles, env_profile_overrides, source="local model environment")

    if not (legacy and not new_configuration):
        _reject_role_alias_conflicts(
            toml_values.get("_local_model_roles"),
            env_values.get("_local_model_role_env"),
        )
        _apply_role_bindings(
            role_bindings,
            _pairs(toml_values.get("_local_model_roles"), "local_models.roles"),
            "local_models.roles",
        )
        _apply_role_bindings(
            role_bindings,
            _pairs(env_values.get("_local_model_role_env"), "local model environment roles"),
            "local model environment roles",
        )

    role_limits: dict[str, object] = dict(_DEFAULT_LOCAL_ROLE_LIMITS)
    if legacy and not new_configuration:
        role_limits["conversation"] = legacy_profile.get(
            "max_output_tokens", _DEFAULT_LOCAL_ROLE_LIMITS["conversation"]
        )
    else:
        _reject_role_limit_alias_conflicts(
            toml_values.get("_local_model_role_limits"),
            env_values.get("_local_model_role_limit_env"),
        )
        _apply_role_limits(
            role_limits,
            _pairs(
                toml_values.get("_local_model_role_limits"),
                "local_models.role_limits",
            ),
            "local_models.role_limits",
        )
        _apply_role_limits(
            role_limits,
            _pairs(
                env_values.get("_local_model_role_limit_env"),
                "local model environment role limits",
            ),
            "local model environment role limits",
        )

    resolved_profiles = tuple(
        LocalModelProfile(
            name=name,
            provider=cast(str, fields.get("provider", "")),
            model_id=cast(str, fields.get("model_id", "")),
            base_url=cast(str, fields.get("base_url", "")),
            timeout_seconds=_as_float(
                fields.get("timeout_seconds"),
                f"local model profile {name} timeout_seconds",
                strictly_positive=True,
            ),
        )
        for name, fields in sorted(profiles.items())
    )
    by_name = {profile.name: profile for profile in resolved_profiles}
    role_configs = tuple(
        LocalModelRoleConfig(
            role=role,
            profile=by_name[profile_name]
            if profile_name in by_name
            else (_raise_unknown_profile(profile_name)),
            max_output_tokens=_as_positive_int(role_limits[role], f"{role}_max_output_tokens"),
        )
        for role in _LOCAL_MODEL_ROLES
        for profile_name in (role_bindings[role],)
    )
    return resolved_profiles, role_configs


def _raise_unknown_profile(name: str) -> NoReturn:
    raise ConfigInvalidError(f"unknown local model profile: {name}")


def _warn_legacy_configuration(
    toml_values: dict[str, object], env_values: dict[str, object]
) -> None:
    """Emit one bounded warning for any accepted migration-era input."""

    if any(
        bool(values.get(marker))
        for values in (toml_values, env_values)
        for marker in (
            "_legacy_generalist_configured",
            "_legacy_pricing_configured",
            "_legacy_role_alias_configured",
        )
    ):
        logging.getLogger("elly.config").warning(
            "deprecated configuration aliases were accepted; migrate to canonical "
            "local_models roles/profiles and remote_call_reservation_usd settings"
        )


def _reject_cross_source_pricing_conflict(
    toml_values: dict[str, object], env_values: dict[str, object]
) -> None:
    if toml_values.get("_legacy_pricing_configured") and (
        "remote_call_reservation_usd" in env_values
    ):
        raise ConfigInvalidError(
            "configure only one remote_call_reservation_usd source when using the "
            "deprecated provider_call_cost_usd alias"
        )
    if env_values.get("_legacy_pricing_configured") and (
        "remote_call_reservation_usd" in toml_values
    ):
        raise ConfigInvalidError(
            "configure only one remote_call_reservation_usd source when using the "
            "deprecated provider_call_cost_usd alias"
        )


def load_config(toml_path: str | None = None) -> Config:
    """Return validated settings with independent local-model role bindings."""
    toml_values = _from_toml(toml_path) if toml_path else {}
    env_values = _from_env()
    _reject_cross_source_pricing_conflict(toml_values, env_values)
    _warn_legacy_configuration(toml_values, env_values)
    merged: dict[str, object] = dict(_DEFAULTS)
    merged.update(toml_values)
    merged.update(env_values)

    log_level = str(merged["log_level"]).upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigInvalidError(f"log_level invalid: {log_level}")
    db_path = str(merged["db_path"])
    if not db_path.strip():
        raise ConfigInvalidError("db_path must be non-empty")

    local_profiles, local_roles = _build_local_roles(merged, toml_values, env_values)
    role_by_name = {role.role: role for role in local_roles}

    max_steps = _as_positive_int(merged["max_steps"], "max_steps")
    max_plan_steps = _as_positive_int(merged["max_plan_steps"], "max_plan_steps")
    max_specialist_executions = _as_nonnegative_int(
        merged["max_specialist_executions"], "max_specialist_executions"
    )
    max_research_executions = _as_nonnegative_int(
        merged["max_research_executions"], "max_research_executions"
    )
    max_synthesis_executions = _as_nonnegative_int(
        merged["max_synthesis_executions"], "max_synthesis_executions"
    )
    max_replanning_attempts = _as_nonnegative_int(
        merged["max_replanning_attempts"], "max_replanning_attempts"
    )
    max_parallel_steps = _as_positive_int(merged["max_parallel_steps"], "max_parallel_steps")
    recursive_planning = _as_bool(merged["recursive_planning"], "recursive_planning")
    specialist_delegation = _as_bool(merged["specialist_delegation"], "specialist_delegation")
    automatic_replanning = _as_bool(merged["automatic_replanning"], "automatic_replanning")
    if max_plan_steps > max_steps:
        raise ConfigInvalidError("max_plan_steps cannot exceed max_steps")
    if max_replanning_attempts > 1:
        raise ConfigInvalidError("max_replanning_attempts cannot exceed the compiled V3 maximum")
    max_provider_calls = _as_positive_int(merged["max_provider_calls"], "max_provider_calls")
    max_retries = _as_nonnegative_int(merged["max_retries"], "max_retries")
    max_concurrency = _as_positive_int(merged["max_concurrency"], "max_concurrency")
    if max_parallel_steps > max_concurrency:
        raise ConfigInvalidError("max_parallel_steps cannot exceed max_concurrency")
    max_queue_size = _as_nonnegative_int(merged["max_queue_size"], "max_queue_size")
    tool_timeout_seconds = _as_float(
        merged["tool_timeout_seconds"], "tool_timeout_seconds", strictly_positive=True
    )
    total_timeout_seconds = _as_float(
        merged["total_timeout_seconds"], "total_timeout_seconds", strictly_positive=True
    )
    monthly_budget_usd = _as_float(merged["monthly_budget_usd"], "monthly_budget_usd")
    remote_call_reservation_usd = _as_float(
        merged["remote_call_reservation_usd"], "remote_call_reservation_usd"
    )
    consent_max_cost_usd = _as_float(merged["consent_max_cost_usd"], "consent_max_cost_usd")
    research_provider = str(merged["research_provider"]).lower()
    if research_provider not in {"openai_web_search", "fixtures"}:
        raise ConfigInvalidError("research_provider must be openai_web_search or fixtures")
    specialist_provider = str(merged["specialist_provider"]).lower()
    if specialist_provider not in {"openai", "fake"}:
        raise ConfigInvalidError("specialist_provider must be openai or fake")
    research_max_results = _as_positive_int(merged["research_max_results"], "research_max_results")
    research_max_output_tokens = _as_positive_int(
        merged["research_max_output_tokens"], "research_max_output_tokens"
    )
    research_timeout_seconds = _as_float(
        merged["research_timeout_seconds"],
        "research_timeout_seconds",
        strictly_positive=True,
    )
    session_retention_days = _as_positive_int(
        merged["session_retention_days"], "session_retention_days"
    )
    evidence_retention_days = _as_positive_int(
        merged["evidence_retention_days"], "evidence_retention_days"
    )
    audit_retention_days = _as_positive_int(merged["audit_retention_days"], "audit_retention_days")
    for key in (
        "app_name",
        "research_model_id",
        "specialist_default_model_id",
        "specialist_manifest_dir",
        "backup_dir",
    ):
        if not str(merged[key]).strip():
            raise ConfigInvalidError(f"{key} must be non-empty")
    raw_overrides = merged["specialist_model_overrides"]
    if not isinstance(raw_overrides, tuple):
        raise ConfigInvalidError("specialist_model_overrides must be a TOML table")
    specialist_model_overrides: list[tuple[str, str]] = []
    for item in raw_overrides:
        if (
            not isinstance(item, tuple)
            or len(item) != 2
            or not str(item[0]).strip()
            or not str(item[1]).strip()
        ):
            raise ConfigInvalidError("specialist model override must have a non-empty id and model")
        specialist_model_overrides.append((str(item[0]), str(item[1])))

    return Config(
        app_name=str(merged["app_name"]),
        db_path=db_path,
        local_model_profiles=local_profiles,
        conversation_role=role_by_name["conversation"],
        planner_role=role_by_name["planner"],
        response_composer_role=role_by_name["response_composer"],
        max_input_chars=_as_positive_int(merged["max_input_chars"], "max_input_chars"),
        context_window_messages=_as_positive_int(
            merged["context_window_messages"], "context_window_messages"
        ),
        specialist_max_output_tokens=_as_positive_int(
            merged["specialist_max_output_tokens"], "specialist_max_output_tokens"
        ),
        log_level=log_level,
        specialist_manifest_dir=str(merged["specialist_manifest_dir"]),
        specialist_provider=specialist_provider,
        specialist_default_model_id=str(merged["specialist_default_model_id"]),
        specialist_model_overrides=tuple(specialist_model_overrides),
        max_steps=max_steps,
        max_plan_steps=max_plan_steps,
        max_specialist_executions=max_specialist_executions,
        max_research_executions=max_research_executions,
        max_synthesis_executions=max_synthesis_executions,
        max_replanning_attempts=max_replanning_attempts,
        max_parallel_steps=max_parallel_steps,
        recursive_planning=recursive_planning,
        specialist_delegation=specialist_delegation,
        automatic_replanning=automatic_replanning,
        max_provider_calls=max_provider_calls,
        max_retries=max_retries,
        tool_timeout_seconds=tool_timeout_seconds,
        total_timeout_seconds=total_timeout_seconds,
        max_concurrency=max_concurrency,
        max_queue_size=max_queue_size,
        monthly_budget_usd=monthly_budget_usd,
        remote_call_reservation_usd=remote_call_reservation_usd,
        consent_max_cost_usd=consent_max_cost_usd,
        research_provider=research_provider,
        research_model_id=str(merged["research_model_id"]),
        research_max_results=research_max_results,
        research_max_output_tokens=research_max_output_tokens,
        research_timeout_seconds=research_timeout_seconds,
        session_retention_days=session_retention_days,
        evidence_retention_days=evidence_retention_days,
        audit_retention_days=audit_retention_days,
        backup_dir=str(merged["backup_dir"]),
    )

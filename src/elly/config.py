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

import os
import tomllib
from dataclasses import dataclass
from urllib.parse import urlsplit

from .domain.errors import ConfigInvalidError


@dataclass(frozen=True, slots=True)
class Config:
    """Validated runtime settings."""

    app_name: str
    db_path: str
    max_input_chars: int
    context_window_messages: int
    generalist_model_id: str
    generalist_provider: str
    generalist_max_output_tokens: int
    specialist_max_output_tokens: int
    log_level: str
    ollama_base_url: str
    ollama_timeout_seconds: float
    specialist_manifest_dir: str
    specialist_provider: str
    specialist_default_model_id: str
    specialist_model_overrides: tuple[tuple[str, str], ...]
    max_steps: int
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

    def specialist_model_id(self, specialist_id: str) -> str:
        """Resolve a specialist model from this one centralized configuration."""
        return dict(self.specialist_model_overrides).get(
            specialist_id, self.specialist_default_model_id
        )

    @property
    def provider_call_cost_usd(self) -> float:
        """Compatibility alias for pre-centralization callers."""
        return self.remote_call_reservation_usd


_DEFAULTS: dict[str, object] = {
    "app_name": "elly",
    "db_path": "data/elly.db",
    "max_input_chars": 20000,
    "context_window_messages": 20,
    "generalist_model_id": "qwen3:8b",
    "generalist_provider": "ollama",
    "generalist_max_output_tokens": 512,
    "specialist_max_output_tokens": 2000,
    "log_level": "INFO",
    "ollama_base_url": "http://127.0.0.1:11434",
    "ollama_timeout_seconds": 120.0,
    "specialist_manifest_dir": "config/specialists",
    "specialist_provider": "openai",
    "specialist_default_model_id": "gpt-5.6-luna",
    "specialist_model_overrides": (),
    "max_steps": 6,
    "max_provider_calls": 2,
    "max_retries": 1,
    "tool_timeout_seconds": 60.0,
    "total_timeout_seconds": 120.0,
    "max_concurrency": 1,
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


def _as_positive_int(value: object, name: str) -> int:
    try:
        ivalue = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigInvalidError(f"{name} must be an integer") from exc
    if ivalue <= 0:
        raise ConfigInvalidError(f"{name} must be > 0")
    return ivalue


def _as_nonnegative_int(value: object, name: str) -> int:
    try:
        ivalue = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigInvalidError(f"{name} must be an integer") from exc
    if ivalue < 0:
        raise ConfigInvalidError(f"{name} must be >= 0")
    return ivalue


def _as_float(value: object, name: str, *, minimum: float = 0.0, strictly_positive: bool = False) -> float:
    try:
        fvalue = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigInvalidError(f"{name} must be a number") from exc
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
    generalist = raw.get("generalist", {})
    log = raw.get("log", {})
    # Central operational selection. These tables are authoritative when both
    # they and a legacy capability-local key are present.
    providers = raw.get("providers", {})
    models = raw.get("models", {})
    pricing = raw.get("pricing", {})
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
    for key in ("max_steps", "max_provider_calls", "max_retries", "max_concurrency", "max_queue_size"):
        if key in limits:
            flat[key] = limits[key]
    for key in ("tool_timeout_seconds", "total_timeout_seconds", "monthly_budget_usd", "provider_call_cost_usd"):
        if key in limits:
            flat["remote_call_reservation_usd" if key == "provider_call_cost_usd" else key] = limits[key]
    research = raw.get("research", {})
    for key in (
        "provider", "model_id", "max_results", "max_output_tokens", "timeout_seconds"
    ):
        if key in research:
            flat[{
                "provider": "research_provider",
                "model_id": "research_model_id",
                "max_results": "research_max_results",
                "max_output_tokens": "research_max_output_tokens",
                "timeout_seconds": "research_timeout_seconds",
            }[key]] = research[key]
    storage = raw.get("storage", {})
    for key in ("session_retention_days", "evidence_retention_days", "audit_retention_days"):
        if key in storage:
            flat[key] = storage[key]
    if "backup_dir" in storage:
        flat["backup_dir"] = storage["backup_dir"]
    if "model_id" in generalist:
        flat["generalist_model_id"] = generalist["model_id"]
    if "provider" in generalist:
        flat["generalist_provider"] = generalist["provider"]
    if "max_output_tokens" in generalist:
        flat["generalist_max_output_tokens"] = generalist["max_output_tokens"]
    if "base_url" in generalist:
        flat["ollama_base_url"] = generalist["base_url"]
    if "timeout_seconds" in generalist:
        flat["ollama_timeout_seconds"] = generalist["timeout_seconds"]
    specialists = raw.get("specialists", {})
    if "manifest_dir" in specialists:
        flat["specialist_manifest_dir"] = specialists["manifest_dir"]
    # New centralized tables override the legacy [generalist], [research], and
    # [limits] locations above, giving operators exactly one edit surface.
    for name, destination in (
        ("generalist", "generalist_provider"),
        ("research", "research_provider"),
        ("specialists", "specialist_provider"),
    ):
        if name in providers:
            flat[destination] = providers[name]
    for name, destination in (
        ("generalist", "generalist_model_id"),
        ("research", "research_model_id"),
        ("specialist_default", "specialist_default_model_id"),
    ):
        if name in models:
            flat[destination] = models[name]
    specialist_models = models.get("specialists", {}) if isinstance(models, dict) else {}
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
            flat[destination] = pricing[name]
    if "level" in log:
        flat["log_level"] = log["level"]
    return flat


def _from_env() -> dict[str, object]:
    env_map = {
        "ELLY_DB_PATH": "db_path",
        "ELLY_MAX_INPUT_CHARS": "max_input_chars",
        "ELLY_CONTEXT_WINDOW_MESSAGES": "context_window_messages",
        "ELLY_GENERALIST_MODEL_ID": "generalist_model_id",
        "ELLY_GENERALIST_PROVIDER": "generalist_provider",
        "ELLY_GENERALIST_MAX_OUTPUT_TOKENS": "generalist_max_output_tokens",
        "ELLY_SPECIALIST_MAX_OUTPUT_TOKENS": "specialist_max_output_tokens",
        "ELLY_LOG_LEVEL": "log_level",
        "ELLY_OLLAMA_BASE_URL": "ollama_base_url",
        "ELLY_OLLAMA_TIMEOUT_SECONDS": "ollama_timeout_seconds",
        "ELLY_SPECIALIST_MANIFEST_DIR": "specialist_manifest_dir",
        "ELLY_SPECIALIST_PROVIDER": "specialist_provider",
        "ELLY_SPECIALIST_DEFAULT_MODEL_ID": "specialist_default_model_id",
        "ELLY_MAX_STEPS": "max_steps",
        "ELLY_MAX_PROVIDER_CALLS": "max_provider_calls",
        "ELLY_MAX_RETRIES": "max_retries",
        "ELLY_TOOL_TIMEOUT_SECONDS": "tool_timeout_seconds",
        "ELLY_TOTAL_TIMEOUT_SECONDS": "total_timeout_seconds",
        "ELLY_MAX_CONCURRENCY": "max_concurrency",
        "ELLY_MAX_QUEUE_SIZE": "max_queue_size",
        "ELLY_MONTHLY_BUDGET_USD": "monthly_budget_usd",
        "ELLY_PROVIDER_CALL_COST_USD": "remote_call_reservation_usd",
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
    return out


def load_config(toml_path: str | None = None) -> Config:
    """Return a validated Config. Raise ConfigInvalidError on any invalid value."""
    merged: dict[str, object] = dict(_DEFAULTS)
    if toml_path:
        merged.update(_from_toml(toml_path))
    merged.update(_from_env())

    log_level = str(merged["log_level"]).upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigInvalidError(f"log_level invalid: {log_level}")

    db_path = str(merged["db_path"])
    if not db_path.strip():
        raise ConfigInvalidError("db_path must be non-empty")
    timeout_seconds = _as_float(merged["ollama_timeout_seconds"], "ollama_timeout_seconds", strictly_positive=True)
    ollama_base_url = str(merged["ollama_base_url"]).rstrip("/")
    parsed_ollama_url = urlsplit(ollama_base_url)
    try:
        ollama_port = parsed_ollama_url.port
    except ValueError as exc:
        raise ConfigInvalidError("ollama_base_url has an invalid port") from exc
    if (
        parsed_ollama_url.scheme != "http"
        or parsed_ollama_url.hostname != "127.0.0.1"
        or ollama_port is None
        or parsed_ollama_url.username is not None
        or parsed_ollama_url.password is not None
        or parsed_ollama_url.path not in {"", "/"}
        or parsed_ollama_url.query
        or parsed_ollama_url.fragment
    ):
        raise ConfigInvalidError("ollama_base_url must be an origin on 127.0.0.1 over HTTP")
    provider = str(merged["generalist_provider"]).lower()
    if provider not in {"fake", "ollama"}:
        raise ConfigInvalidError("generalist_provider must be fake or ollama")
    max_steps = _as_positive_int(merged["max_steps"], "max_steps")
    max_provider_calls = _as_positive_int(merged["max_provider_calls"], "max_provider_calls")
    max_retries = _as_nonnegative_int(merged["max_retries"], "max_retries")
    max_concurrency = _as_positive_int(merged["max_concurrency"], "max_concurrency")
    max_queue_size = _as_nonnegative_int(merged["max_queue_size"], "max_queue_size")
    tool_timeout_seconds = _as_float(merged["tool_timeout_seconds"], "tool_timeout_seconds", strictly_positive=True)
    total_timeout_seconds = _as_float(merged["total_timeout_seconds"], "total_timeout_seconds", strictly_positive=True)
    monthly_budget_usd = _as_float(merged["monthly_budget_usd"], "monthly_budget_usd")
    remote_call_reservation_usd = _as_float(
        merged["remote_call_reservation_usd"], "remote_call_reservation_usd"
    )
    consent_max_cost_usd = _as_float(
        merged["consent_max_cost_usd"], "consent_max_cost_usd"
    )
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
    research_timeout_seconds = _as_float(merged["research_timeout_seconds"], "research_timeout_seconds", strictly_positive=True)
    session_retention_days = _as_positive_int(merged["session_retention_days"], "session_retention_days")
    evidence_retention_days = _as_positive_int(
        merged["evidence_retention_days"], "evidence_retention_days"
    )
    audit_retention_days = _as_positive_int(
        merged["audit_retention_days"], "audit_retention_days"
    )
    for key in (
        "app_name", "generalist_model_id", "research_model_id",
        "specialist_default_model_id", "specialist_manifest_dir", "backup_dir",
    ):
        if not str(merged[key]).strip():
            raise ConfigInvalidError(f"{key} must be non-empty")
    raw_overrides = merged["specialist_model_overrides"]
    if not isinstance(raw_overrides, tuple):
        raise ConfigInvalidError("specialist_model_overrides must be a TOML table")
    specialist_model_overrides: list[tuple[str, str]] = []
    for item in raw_overrides:
        if (not isinstance(item, tuple) or len(item) != 2
                or not str(item[0]).strip() or not str(item[1]).strip()):
            raise ConfigInvalidError("specialist model override must have a non-empty id and model")
        specialist_model_overrides.append((str(item[0]), str(item[1])))

    return Config(
        app_name=str(merged["app_name"]),
        db_path=db_path,
        max_input_chars=_as_positive_int(merged["max_input_chars"], "max_input_chars"),
        context_window_messages=_as_positive_int(
            merged["context_window_messages"], "context_window_messages"
        ),
        generalist_model_id=str(merged["generalist_model_id"]),
        generalist_provider=provider,
        generalist_max_output_tokens=_as_positive_int(
            merged["generalist_max_output_tokens"], "generalist_max_output_tokens"
        ),
        specialist_max_output_tokens=_as_positive_int(
            merged["specialist_max_output_tokens"], "specialist_max_output_tokens"
        ),
        log_level=log_level,
        ollama_base_url=ollama_base_url,
        ollama_timeout_seconds=timeout_seconds,
        specialist_manifest_dir=str(merged["specialist_manifest_dir"]),
        specialist_provider=specialist_provider,
        specialist_default_model_id=str(merged["specialist_default_model_id"]),
        specialist_model_overrides=tuple(specialist_model_overrides),
        max_steps=max_steps,
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

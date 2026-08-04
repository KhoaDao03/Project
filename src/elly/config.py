"""Configuration loading and validation (OPS-002/M3).

Responsibility: assemble validated runtime settings from, in order:
  1. built-in conservative defaults (mirrors config.example.toml),
  2. an optional TOML file,
  3. ELLY_* environment overrides.
Invalid configuration fails closed with ConfigInvalidError (never a silent
default substitution for a bad value) — OPS-002 / NFR-001 intent.

M2 carries no credentials: Ollama is localhost-only (SEC-004).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass

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
    log_level: str
    ollama_base_url: str
    ollama_timeout_seconds: float
    specialist_manifest_dir: str
    max_steps: int
    max_provider_calls: int
    max_retries: int
    tool_timeout_seconds: float
    total_timeout_seconds: float
    max_concurrency: int
    max_queue_size: int
    monthly_budget_usd: float
    provider_call_cost_usd: float


_DEFAULTS: dict[str, object] = {
    "app_name": "elly",
    "db_path": "data/elly.db",
    "max_input_chars": 20000,
    "context_window_messages": 20,
    "generalist_model_id": "qwen3:8b",
    "generalist_provider": "ollama",
    "generalist_max_output_tokens": 512,
    "log_level": "INFO",
    "ollama_base_url": "http://127.0.0.1:11434",
    "ollama_timeout_seconds": 120.0,
    "specialist_manifest_dir": "config/specialists",
    "max_steps": 6,
    "max_provider_calls": 2,
    "max_retries": 1,
    "tool_timeout_seconds": 60.0,
    "total_timeout_seconds": 120.0,
    "max_concurrency": 1,
    "max_queue_size": 1,
    "monthly_budget_usd": 10.0,
    "provider_call_cost_usd": 0.0,
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
    if "name" in app:
        flat["app_name"] = app["name"]
    if "db_path" in app:
        flat["db_path"] = app["db_path"]
    if "max_input_chars" in limits:
        flat["max_input_chars"] = limits["max_input_chars"]
    if "context_window_messages" in limits:
        flat["context_window_messages"] = limits["context_window_messages"]
    for key in ("max_steps", "max_provider_calls", "max_retries", "max_concurrency", "max_queue_size"):
        if key in limits:
            flat[key] = limits[key]
    for key in ("tool_timeout_seconds", "total_timeout_seconds", "monthly_budget_usd", "provider_call_cost_usd"):
        if key in limits:
            flat[key] = limits[key]
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
        "ELLY_LOG_LEVEL": "log_level",
        "ELLY_OLLAMA_BASE_URL": "ollama_base_url",
        "ELLY_OLLAMA_TIMEOUT_SECONDS": "ollama_timeout_seconds",
        "ELLY_SPECIALIST_MANIFEST_DIR": "specialist_manifest_dir",
        "ELLY_MAX_STEPS": "max_steps",
        "ELLY_MAX_PROVIDER_CALLS": "max_provider_calls",
        "ELLY_MAX_RETRIES": "max_retries",
        "ELLY_TOOL_TIMEOUT_SECONDS": "tool_timeout_seconds",
        "ELLY_TOTAL_TIMEOUT_SECONDS": "total_timeout_seconds",
        "ELLY_MAX_CONCURRENCY": "max_concurrency",
        "ELLY_MAX_QUEUE_SIZE": "max_queue_size",
        "ELLY_MONTHLY_BUDGET_USD": "monthly_budget_usd",
        "ELLY_PROVIDER_CALL_COST_USD": "provider_call_cost_usd",
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
    if not ollama_base_url.startswith("http://127.0.0.1:"):
        raise ConfigInvalidError("ollama_base_url must use localhost HTTP")
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
    provider_call_cost_usd = _as_float(merged["provider_call_cost_usd"], "provider_call_cost_usd")

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
        log_level=log_level,
        ollama_base_url=ollama_base_url,
        ollama_timeout_seconds=timeout_seconds,
        specialist_manifest_dir=str(merged["specialist_manifest_dir"]),
        max_steps=max_steps,
        max_provider_calls=max_provider_calls,
        max_retries=max_retries,
        tool_timeout_seconds=tool_timeout_seconds,
        total_timeout_seconds=total_timeout_seconds,
        max_concurrency=max_concurrency,
        max_queue_size=max_queue_size,
        monthly_budget_usd=monthly_budget_usd,
        provider_call_cost_usd=provider_call_cost_usd,
    )

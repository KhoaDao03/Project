"""Configuration loading and validation (OPS-002 initial).

Responsibility: assemble validated runtime settings from, in order:
  1. built-in conservative defaults (mirrors config.example.toml),
  2. an optional TOML file,
  3. ELLY_* environment overrides.
Invalid configuration fails closed with ConfigInvalidError (never a silent
default substitution for a bad value) — OPS-002 / NFR-001 intent.

M1 carries NO secrets and NO provider credentials (SEC-004): there is nothing to
resolve for Ollama/OpenAI/Brave here.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass

from .domain.errors import ConfigInvalidError


@dataclass(frozen=True, slots=True)
class Config:
    """Validated M1 settings."""

    app_name: str
    db_path: str
    max_input_chars: int
    context_window_messages: int
    generalist_model_id: str
    generalist_max_output_tokens: int
    log_level: str


_DEFAULTS: dict[str, object] = {
    "app_name": "elly",
    "db_path": "data/elly.db",
    "max_input_chars": 20000,
    "context_window_messages": 20,
    "generalist_model_id": "fake-generalist-v1",
    "generalist_max_output_tokens": 512,
    "log_level": "INFO",
}


def _as_positive_int(value: object, name: str) -> int:
    try:
        ivalue = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigInvalidError(f"{name} must be an integer") from exc
    if ivalue <= 0:
        raise ConfigInvalidError(f"{name} must be > 0")
    return ivalue


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
    if "model_id" in generalist:
        flat["generalist_model_id"] = generalist["model_id"]
    if "max_output_tokens" in generalist:
        flat["generalist_max_output_tokens"] = generalist["max_output_tokens"]
    if "level" in log:
        flat["log_level"] = log["level"]
    return flat


def _from_env() -> dict[str, object]:
    env_map = {
        "ELLY_DB_PATH": "db_path",
        "ELLY_MAX_INPUT_CHARS": "max_input_chars",
        "ELLY_CONTEXT_WINDOW_MESSAGES": "context_window_messages",
        "ELLY_GENERALIST_MODEL_ID": "generalist_model_id",
        "ELLY_GENERALIST_MAX_OUTPUT_TOKENS": "generalist_max_output_tokens",
        "ELLY_LOG_LEVEL": "log_level",
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

    return Config(
        app_name=str(merged["app_name"]),
        db_path=db_path,
        max_input_chars=_as_positive_int(merged["max_input_chars"], "max_input_chars"),
        context_window_messages=_as_positive_int(
            merged["context_window_messages"], "context_window_messages"
        ),
        generalist_model_id=str(merged["generalist_model_id"]),
        generalist_max_output_tokens=_as_positive_int(
            merged["generalist_max_output_tokens"], "generalist_max_output_tokens"
        ),
        log_level=log_level,
    )

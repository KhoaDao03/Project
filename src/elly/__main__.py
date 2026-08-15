"""Application entry point: `python -m elly` (or the `elly` script).

Wires the app via the composition root and starts the terminal REPL. Configuration
comes from an optional TOML path (--config) plus ELLY_* env vars. On a
configuration error it fails closed with a clear message and non-zero exit.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .composition import build
from .domain.errors import ConfigInvalidError, StorageFailureError
from .dotenv import load_dotenv
from .presentation.cli import Cli


def main(argv: list[str] | None = None) -> int:
    """Build the configured application, run the CLI, and return a process code."""
    # Load local secrets/env from .env (SEC-004): non-overriding, no-op if absent.
    load_dotenv()

    parser = argparse.ArgumentParser(prog="elly", description="Elly local-first assistant")
    parser.add_argument(
        "--config", default=None,
        help="path to a TOML config file (defaults to ./config.local.toml when present)",
    )
    args = parser.parse_args(argv)
    config_path = args.config
    if config_path is None and Path("config.local.toml").is_file():
        config_path = "config.local.toml"

    try:
        app = build(config_path)
    except (ConfigInvalidError, StorageFailureError) as exc:
        print(f"Startup failed: {exc.summary}", file=sys.stderr)
        return 2

    try:
        Cli.start(app).run()
    finally:
        app.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""Application entry point: `python -m elly` (or the `elly` script).

Wires the app via the composition root and starts the terminal REPL. Configuration
comes from an optional TOML path (--config) plus ELLY_* env vars. On a
configuration error it fails closed with a clear message and non-zero exit.
"""

from __future__ import annotations

import argparse
import sys

from .composition import build
from .domain.errors import ConfigInvalidError, StorageFailureError
from .dotenv import load_dotenv
from .presentation.cli import Cli


def main(argv: list[str] | None = None) -> int:
    # Load local secrets/env from .env (SEC-004): non-overriding, no-op if absent.
    load_dotenv()

    parser = argparse.ArgumentParser(prog="elly", description="Elly M1 walking skeleton")
    parser.add_argument("--config", default=None, help="path to a TOML config file (optional)")
    args = parser.parse_args(argv)

    try:
        app = build(args.config)
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

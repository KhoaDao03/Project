"""Minimal `.env` loader (stdlib only) — SEC-004.

Loads `KEY=VALUE` lines from a `.env` file into `os.environ` so local secrets (e.g.
`OPENAI_API_KEY`) stay out of version control and out of code. Deliberately tiny — no
third-party dependency (Elly's runtime is stdlib-only).

Rules:
- non-overriding by default: a real shell/CI environment variable WINS over `.env`;
- skips blank lines, `#` comments, and **empty values** (so an unfilled key is a no-op);
- strips optional surrounding quotes and a leading `export `;
- missing file is fine (returns `[]`).

Never logs or returns VALUES — only the names loaded, for optional debug output.
`.env` is gitignored; `.env.example` is the committed template.
"""

from __future__ import annotations

import os


def load_dotenv(path: str = ".env", *, override: bool = False) -> list[str]:
    """Load `path` into os.environ. Return the list of KEY names actually set."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except FileNotFoundError:
        return []
    except OSError:
        return []

    loaded: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key or not value:
            continue  # unfilled placeholder -> leave unset
        if not override and key in os.environ:
            continue  # real environment wins
        os.environ[key] = value
        loaded.append(key)
    return loaded

# Elly

Elly Research Assistant — a local-first personal AI assistant.

**Current state: Milestone M1 (Walking Skeleton) — implemented, fake-backed by
design.** Ordinary local conversation runs end-to-end through a deterministic
**fake** generalist (the real Ollama model is Milestone M2). See
[`docs/MILESTONE_PLAN.md`](docs/MILESTONE_PLAN.md) for the roadmap and
[`docs/M1_IMPLEMENTATION_STATUS.md`](docs/M1_IMPLEMENTATION_STATUS.md) for exactly
what is real vs fake vs unavailable.

## Requirements

Python **≥ 3.11**. **No third-party runtime dependencies** — M1 uses only the
standard library (`sqlite3`, `tomllib`, `dataclasses`, …).

## Run

```bash
PYTHONPATH=src python3 -m elly                          # uses built-in defaults / ELLY_* env
PYTHONPATH=src python3 -m elly --config config.example.toml
ELLY_DB_PATH=":memory:" PYTHONPATH=src python3 -m elly  # ephemeral database
```

### Commands

| Command | Effect |
|---|---|
| `<text>` | Ask Elly (local, fake generalist) |
| `/new [--no-store]` | Start a new session (optionally no-store) |
| `/mode local` | Local-only (the only mode in M1) |
| `/mode cloud` | **Unavailable in M1** (cloud specialists = M5) |
| `/status` | Dependency health + active mode |
| `/cancel` | **Unavailable in M1** (cancellation = M2/M3) |
| `/help`, `/exit` | Help / quit |

## Configuration

Defaults live in code; override via `config.example.toml` (copy to
`config.local.toml`) or `ELLY_*` env vars (e.g. `ELLY_DB_PATH`,
`ELLY_MAX_INPUT_CHARS`, `ELLY_LOG_LEVEL`). The M1 runtime uses **no secrets** (the
generalist is a fake).

**Secrets (`.env`).** For later cloud use (and the M0 OpenAI feasibility smoke), copy
`.env.example` to `.env` and paste your key:

```bash
cp .env.example .env      # then set OPENAI_API_KEY=... in .env
```

`.env` is gitignored (never committed, SEC-004); `.env.example` is the committed
template. `python -m elly` loads `.env` at startup (non-overriding; empty values
ignored), so an unfilled key is a safe no-op.

## Test

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t .                            # all tests
PYTHONPATH=src python3 -W error::ResourceWarning -m unittest discover -s tests -t .  # strict
PYTHONPATH=src python3 -m compileall -q src tests                                    # syntax check
```

## Real vs fake dependencies (M1)

- **Real:** terminal CLI, deterministic orchestrator, SQLite persistence (honors
  no-store), redacted audit log, config, health.
- **Fake:** the generalist model (`FakeGeneralist`) — deterministic, offline; the
  real Ollama adapter arrives in M2.

## Limitations

Fake-backed conversation only (no real model, so no genuine answer quality or
in-session reference resolution yet). No web/RAG, cloud specialists, memory/profile,
or resource-limit framework — those are later milestones. Not for production
(personal prototype).

## Layout

```
src/elly/{domain,ports,adapters,application,presentation}/   # ports-and-adapters monolith
tests/                                                       # stdlib unittest
docs/                                                        # SRS, DESIGN, plan, guides
```

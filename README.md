# Elly

Elly Research Assistant — a local-first personal AI assistant.

**Current state: Milestone M3 — guardrail spine implemented.** Development and
testing default to local `qwen3:8b`; `qwen3:14b` is
opt-in through [config.qwen3-14b.example.toml](config.qwen3-14b.example.toml) or
`ELLY_GENERALIST_MODEL_ID`. See
[`docs/MILESTONE_PLAN.md`](docs/MILESTONE_PLAN.md) for the roadmap and
[`docs/M3_IMPLEMENTATION_STATUS.md`](docs/M3_IMPLEMENTATION_STATUS.md) for the
guardrail implementation and verification status.

## Requirements

Python **≥ 3.11**. **No third-party runtime dependencies** — M3 uses only the
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
| `<text>` | Ask Elly (local Ollama generalist) |
| `/new [--no-store]` | Start a new session (optionally no-store) |
| `/mode local` | Local-only (the only available mode in M3) |
| `/mode cloud` | **Unavailable in M1** (cloud specialists = M5) |
| `/status` | Dependency health + active mode |
| `/cancel` | Request cancellation of the active local generation |
| `/help`, `/exit` | Help / quit |

## Configuration

Defaults live in code; override via `config.example.toml` (copy to
`config.local.toml`) or `ELLY_*` env vars (e.g. `ELLY_DB_PATH`,
`ELLY_MAX_INPUT_CHARS`, `ELLY_LOG_LEVEL`). M2 sends prompts only to the configured
localhost Ollama endpoint; no cloud provider or secret is used.

M3 guardrails are configurable through the `[limits]` section or `ELLY_*`
environment variables: steps, provider calls, retries, concurrency, queue size,
timeouts, output tokens, and the authoritative monthly budget.

`config/specialists/*.toml` contains declarative specialist manifests. They are
validated and discovered at startup, but specialist routing/execution is deferred
to M5.

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

## Real vs fake dependencies (M3)

- **Real:** terminal CLI, deterministic orchestrator, SQLite persistence (honors
  no-store), redacted audit log, config, health.
- **Real:** the local generalist (`OllamaGeneralist`) for non-`fake-*` model IDs.
- **Fake:** `FakeGeneralist`, retained for deterministic contract and unit tests.

## Limitations

No web/RAG, cloud specialists, memory/profile, backup/restore, or live cost pricing
are implemented. Not for production (personal prototype).

## Layout

```
src/elly/{domain,ports,adapters,application,presentation}/   # ports-and-adapters monolith
tests/                                                       # stdlib unittest
docs/                                                        # SRS, DESIGN, plan, guides
```

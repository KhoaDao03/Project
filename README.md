# Elly

Elly Research Assistant — a local-first personal AI assistant.

**Current state: independently verified, not release-ready.** M0–M2 remain closed,
M3–M6 are reopened, and M7 remains open for aggregate quality evidence and owner
UAT. See [`docs/V1_VERIFICATION_REPORT.md`](docs/V1_VERIFICATION_REPORT.md).
Development and testing default to local `qwen3:8b`; `qwen3:14b` is
opt-in through [config.qwen3-14b.example.toml](config.qwen3-14b.example.toml) or
`ELLY_GENERALIST_MODEL_ID`. See
[`docs/MILESTONE_PLAN.md`](docs/MILESTONE_PLAN.md) for the roadmap and
[`docs/implementStatus/M6_IMPLEMENTATION_STATUS.md`](docs/implementStatus/M6_IMPLEMENTATION_STATUS.md)
for M6 implementation status and [`docs/M7_RELEASE_CHECKLIST.md`](docs/M7_RELEASE_CHECKLIST.md)
for current release-gate evidence. See
[`docs/implementStatus/M7_IMPLEMENTATION_STATUS.md`](docs/implementStatus/M7_IMPLEMENTATION_STATUS.md)
for the M7 implementation status.

## Requirements

Python **≥ 3.11**. **No third-party runtime dependencies** — V1 uses only the
standard library (`sqlite3`, `tomllib`, `dataclasses`, …).

## Run

```bash
cp config.example.toml config.local.toml                # one-time local setup
PYTHONPATH=src python3 -m elly                          # auto-loads config.local.toml
PYTHONPATH=src python3 -m elly --config config.example.toml
ELLY_DB_PATH=":memory:" PYTHONPATH=src python3 -m elly  # ephemeral database
```

### Commands

| Command | Effect |
|---|---|
| `<text>` | Ask Elly (local Ollama generalist) |
| `/new [--no-store]` | Start a new session (optionally no-store) |
| `/mode local` | Local-only (the default mode) |
| `/mode cloud` | Permit policy-controlled hosted web research (OpenAI `web_search`) |
| `/status` | Dependency health + active mode |
| `/cancel` | Request cancellation of the active local generation |
| `/approve <id>` | Approve one exact specialist consent proposal |
| `/deny <id>` | Deny one specialist consent proposal |
| `/profile ...` | Review, add, correct, or delete confirmed profile items |
| `/history list\|delete ...` | Review or delete stored sessions |
| `/trace <task-id>` | Show redacted durable task events |
| `/sources <task-id>` | Show task source metadata |
| `/backup <path>` / `/restore <path>` | Create or restore an authenticated backup |
| `/help`, `/exit` | Help / quit |

## Configuration

Copy `config.example.toml` to the gitignored `config.local.toml`. A normal
`python -m elly` run auto-loads that file, so `--config` is needed only for an
alternate profile. Operational choices are centralized:

- `[providers]` selects generalist, research, and specialist adapters.
- `[models]` selects the local model, research model, and default specialist
  model; `[models.specialists]` can override an individual specialist.
- `[pricing]` owns the monthly ceiling, remote-call reservation, and consent maximum.

Specialist manifests contain capability/security policy, not provider, model, or
dollar pricing. Environment variables remain optional deployment overrides; API
keys still belong only in `.env` or the OS environment.

M3/M4 guardrails are configurable through `[limits]`; pricing is in `[pricing]`.
Optional `ELLY_*` environment variables can override deployment-specific values.

M6 retention and backup settings are in `[storage]`; set `ELLY_BACKUP_KEY` to
enable startup and hourly daily-backup checks plus `/backup`/`/restore`.

`config/specialists/*.toml` contains declarative capability manifests. They are
validated and discovered at startup. Research and coding routes may use the
centrally configured specialist provider only in cloud-permitted mode and under
privacy/consent policy.

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

## Real vs fake dependencies

- **Real:** terminal CLI, deterministic orchestrator, SQLite persistence (honors
  no-store), redacted audit log, config, health.
- **Real:** the local generalist (`OllamaGeneralist`) for non-`fake-*` model IDs.
- **Fake:** `FakeGeneralist`, retained for deterministic contract and unit tests.
- **Real:** approved OpenAI hosted `web_search` when `OPENAI_API_KEY` is configured.
- **Fake:** `FixtureWebResearchProvider`, used for deterministic research tests.

## Limitations

Hosted-search metadata does not currently prove claim-level support, so live
research may return `unknown` with validated sources. Full page-body RAG and M7
quality/UAT gates remain incomplete. Brave/local reading, semantic memory, and
authoritative live billing prices remain deferred. Specialists never execute
tools, write files, or perform high-impact actions. Not for production.

## Layout

```
src/elly/{domain,ports,adapters,application,presentation}/   # ports-and-adapters monolith
tests/                                                       # stdlib unittest
docs/                                                        # SRS, DESIGN, plan, guides
```

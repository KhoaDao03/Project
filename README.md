# Elly

Elly is a terminal-first, local-first personal AI assistant. Ordinary conversation
runs through a local Ollama model. When the owner explicitly enables cloud mode,
Elly can route current-information questions to hosted web research and selected
tasks to hosted specialists under privacy, consent, cost, and execution limits.

## Project context and documentation

Future developers and AI agents should read [PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md)
first. It is the maintained, up-to-date orientation and handoff snapshot for the
project, including current scope, architecture, workflows, milestone status,
verification evidence, limitations, unresolved decisions, and recommended reading
order. It is intended to provide immediate context without requiring a review of
every document or prior conversation.

The project context is a navigation and summary layer, not a replacement for
authoritative requirements, decisions, source code, tests, or verification reports.
When deeper understanding or exact behavior is needed, those materials remain
available in this repository and should be consulted directly.

For a detailed end-to-end explanation of the complete V1 and V1.5 project, see
the [Project Guide](docs/PROJECT_GUIDE.md). It covers the architecture,
ports/adapters, workflows, Ollama, hosted research, document retrieval,
persistence, testing, limitations, and interview preparation.

Version-specific documentation should be grouped under the corresponding
documentation folder, such as `docs/v1/`, so that requirements, architecture,
decisions, implementation records, tests, and verification evidence for that
version can be found together. The project context should link to the relevant
version documents and be updated whenever project behavior, scope, decisions,
milestones, or verification status changes.

## Project status

**V3 completed and closed by owner request.** As of **2026-08-16**, all 13 V3
requirements and Phases 0–9 are implemented and deterministically verified. The
public submission path now performs local typed planning, deterministic DAG
validation, bounded execution, per-step authorization, typed aggregation, and
evidence-bounded local synthesis. The full 457-test suite, 100 concurrency and
cancellation stress runs, Ruff, strict MyPy across 118 source files, compilation,
and whitespace checks pass. Live local planner and synthesis checks passed with
`qwen3:8b`; hosted-provider live verification is explicitly deferred because no
credentials were available. See the [V3 closure record](docs/v3/V3_CLOSURE.md)
and [Phase 9 verification](docs/v3/PHASE_9_VERIFICATION.md).

**V2.5 completed and closed by owner decision.** As of **2026-08-15**, all seven
registry-driven routing requirements and the final legacy-routing removal are
implemented and accepted. The full 368-test suite, Ruff, strict MyPy across 93
source files, compilation, migration coverage, static boundaries, and
whitespace checks pass. Limited live-provider quality verification remains a
declared boundary and is not claimed as passing. See the
[V2.5 closure record](docs/v2.5/V2_5_CLOSURE.md).

**V2 completed and closed by owner decision.** As of **2026-08-15**, all nine
approved V2 requirements are implemented and accepted. The full 314-test suite
passed three consecutive runs; Ruff, strict MyPy across 91 source files,
compilation, migration, and whitespace checks pass. Limited live-provider
quality verification is an accepted deferred exception and is not claimed as
passed. See the [V2 closure record](docs/v2/V2_CLOSURE.md) and
[verification report](docs/v2/V2_IMPLEMENTATION_VERIFICATION.md).

**V1.5 iteration closed by owner decision.** As of **2026-08-07**:

- M0–M2 remain closed.
- M3–M6 are implemented for the current prototype but remain reopened against
  their broader acceptance criteria.
- M7 remains open pending the complete live-quality corpus and owner UC-01…UC-12
  acceptance testing.
- The V1.5 deterministic suite passes: **260 passed, 0 failed, 0 skipped**.
- Ruff, strict mypy across 69 source files, compilation, and whitespace checks pass.
- V1.5 live-provider verification is explicitly deferred and is not claimed as passed.
- The development default is `qwen3:8b`; `qwen3:14b` is available through the
  opt-in [14B example profile](config.qwen3-14b.example.toml).

The historical V1 release gaps remain separate from the closed V1.5 iteration.
See the [V1.5 closure record](docs/v1.5/V1_5_CLOSURE.md),
[V1.5 verification report](docs/v1.5/V1_5_IMPLEMENTATION_VERIFICATION.md), and
[project context](docs/PROJECT_CONTEXT.md).

## What works today

| Area | Current behavior |
|---|---|
| Local conversation | Real localhost Ollama adapter with bounded context, output limits, cancellation, typed failures, and no cloud fallback |
| Conversational awareness | Dependent turns use bounded recent conversation context for routing and answers; unrelated turns do not inherit stale intent |
| Web research | OpenAI hosted `web_search` with `store:false`, required search, bounded retry, URL validation, source selection, and explicit cloud-mode gating |
| Market lookups | Recognized current commodity/index questions require direct quote, exchange, index-administrator, or market-data sources; news, forecasts, and community posts are not accepted as live quotes |
| Evidence honesty | Results distinguish `known`, `inferred`, `unknown`, and `blocked`; metadata-only provider summaries remain visibly unverified |
| Specialists | Coding and evidence-synthesis routes use validated manifests and structured hosted responses with exact consent where policy requires it |
| Privacy | Local-only is the default; restricted data cannot leave the machine, and eligible local/private payloads require an exact one-use consent proposal |
| Persistence | SQLite sessions, confirmed profile items, redacted audit events, task traces, source metadata, independent retention periods, and no-store sessions |
| Operations | Health/status reporting, bounded queue/concurrency, retry/circuit/timeout controls, cost reservations, authenticated backup/restore, and startup maintenance |
| Configuration | Provider, model, and pricing choices are centralized in one TOML file, with environment variables as the final override layer |
| V3 orchestration | Local capability-first planning produces a validated persisted DAG; bounded steps may run in parallel, pause for exact authorization, aggregate partial/disagreement states, and use validated local synthesis or deterministic fallback |

Elly never treats model output as authorization. Specialists cannot execute tools,
write files, or truthfully claim that they performed external actions.

## Requirements

- Python **3.11 or newer**
- Ollama running locally at `http://127.0.0.1:11434` for the default generalist
- The configured local model, normally `qwen3:8b`
- An `OPENAI_API_KEY` only if hosted research or specialists will be used

Elly has **no third-party Python runtime dependencies**; its application runtime
uses the standard library. Ollama and OpenAI are external providers, not Python
packages installed by this project.

## Quick start

From the repository root:

```bash
# One-time local configuration
cp config.example.toml config.local.toml

# Ensure the default local model is available
ollama pull qwen3:8b

# Start Elly; config.local.toml is loaded automatically
PYTHONPATH=src python3 -m elly
```

For hosted capabilities, add the key to the gitignored `.env` file:

```bash
cp .env.example .env
# Edit .env and set OPENAI_API_KEY=...
```

Elly loads `.env` without overriding values already present in the process
environment. API keys do not belong in TOML files.

Alternative launches:

```bash
PYTHONPATH=src python3 -m elly --config config.example.toml
ELLY_DB_PATH=":memory:" PYTHONPATH=src python3 -m elly
```

## Using Elly

Elly starts in `local_only` mode. Cloud mode grants permission for policy-approved
hosted calls; it does not force every message to use a cloud route.

```text
you> Explain dependency injection
... local Ollama response ...
Evidence: inferred
Route: local_generalist

you> /mode cloud
Mode: cloud_permitted (hosted web research requires OPENAI_API_KEY).

you> What is the current S&P 500 index?
... current researched response or an honest inability to verify ...
Evidence: known | inferred | unknown
Route: web_research
```

Follow-ups such as “How about gold?” or “Tell me more” use the relevant bounded
conversation history. Routing authority comes from the user’s intent—not from text
previously generated by the assistant.

### Evidence labels

- `known`: displayed factual claims have a safe claim-supporting cited passage.
- `inferred`: a useful provider or local-model answer is shown, but is not
  established as verified fact.
- `unknown`: evidence is absent, unsuitable, or conflicting.
- `blocked`: policy, consent, configuration, limits, or a provider failure stopped
  the request.

Hosted providers sometimes return valid source metadata without claim-level
passages. In that case Elly separates an **Unverified provider summary** from an
empty **Verified facts** section rather than pretending the links prove the text.

### Commands

| Command | Effect |
|---|---|
| `<text>` | Submit a request through context-aware routing |
| `/new [--no-store]` | Start a stored or ephemeral session |
| `/mode local` | Enforce local-only operation |
| `/mode cloud` | Permit policy-controlled hosted research and specialists |
| `/status` | Show health, resolved providers/models, limits, and budget usage |
| `/cancel` | Request cancellation of active local generation |
| `/approve <id>` | Approve the exact pending specialist/hosted consent proposal |
| `/deny <id>` | Deny the pending proposal without making the call |
| `/profile list\|add\|correct\|delete ...` | Manage explicitly confirmed profile items |
| `/history list\|delete <session-id>` | Review or delete stored sessions |
| `/trace <task-id>` | Show redacted durable task events |
| `/sources <task-id>` | Show stored validated source metadata |
| `/backup <path>` | Create an authenticated backup when `ELLY_BACKUP_KEY` is set |
| `/restore <path>` | Validate and restore an authenticated backup |
| `/help`, `/exit` | Show help or quit |

## One-file runtime configuration

Copy [config.example.toml](config.example.toml) to the gitignored
`config.local.toml`. Remote provider, model, and pricing changes live together;
local conversation, planning, and synthesis use named reusable profiles:

```toml
[providers]
research = "openai_web_search"
specialists = "openai"

[models]
research = "gpt-5.6-luna"
specialist_default = "gpt-5.6-luna"

[local_models.profiles.qwen_default]
provider = "ollama"
model_id = "qwen3:8b"
base_url = "http://127.0.0.1:11434"
timeout_seconds = 120

[local_models.roles]
conversation = "qwen_default"
planner = "qwen_default"
synthesis = "qwen_default"

[local_models.role_limits]
conversation_max_output_tokens = 512
planner_max_output_tokens = 1200
synthesis_max_output_tokens = 1600

[models.specialists]
# coding = "gpt-5.6-terra"
# research = "gpt-5.6-luna"
# stock_analysis = "gpt-5.6-terra"

[pricing]
monthly_budget_usd = 10
remote_call_reservation_usd = 0.01
consent_max_cost_usd = 0.25
```

Additional sections control behavior rather than provider selection. Existing
`[generalist]`, `[providers].generalist`, and `[models].generalist` keys remain
supported during the V3 migration window; new local-model profiles take
precedence when both forms are present.

- `[limits]`: input, steps, calls, retries, timeouts, concurrency, queue, and
  specialist output ceilings.
- `[local_models]`: reusable local profiles, role bindings, and role-specific
  output ceilings.
- `[research]`: maximum sources, 2,048-token default output allowance, and timeout.
- `[storage]`: session/evidence/audit retention and backup directory.
- `[specialists]`: capability-manifest directory.
- `[log]`: redacted structured-log level.

Environment variables remain supported as deployment overrides. Legacy TOML keys
are accepted during migration, but the centralized tables above take precedence.
Run `/status` to see the effective non-secret configuration.

Specialist manifests in `config/specialists/` define capabilities, risk, privacy,
timeouts, and exclusions. They do not duplicate provider models or pricing.
`stock_analysis` is present as a validated capability manifest, but the current
deterministic router exposes only the coding and research-specialist routes; stock
questions that need fresh data currently use web research.

## Research safeguards

For recognized current commodity and financial-index quotes, Elly:

1. anchors search to the exact UTC request time;
2. requests a direct quote and its date/time, delay, and market status;
3. blocks common community domains at the hosted-search layer;
4. rejects news, forecasts, analysis, opinion, and community pages as quote
   evidence during local selection;
5. deduplicates tracking, `www`, and trailing-slash URL variants; and
6. retries once with a targeted citation-repair instruction when the first search
   returns no cited source.

If suitable evidence is still unavailable, Elly abstains instead of substituting
an old article or unsupported value.

## Storage and privacy

- Normal sessions use SQLite and configured retention periods.
- `/new --no-store` prevents message-body reconstruction after restart.
- Only explicitly confirmed profile facts are stored; inferred profile facts have
  no persistence path.
- Audit events contain bounded operational metadata, not prompts, secrets, or
  chain-of-thought.
- Source metadata expires separately from sessions and audit events.
- `ELLY_BACKUP_KEY` enables backup/restore and scheduled daily-backup checks.

The backup mechanism is a prototype authenticated envelope, not a final vetted
AEAD/key-management design. That production decision and recovery acceptance are
still open release items.

## Verification

Run the deterministic checks from the repository root:

```bash
PYTHONPATH=src python3 -W error::ResourceWarning -m unittest discover -s tests -t .
PYTHONPATH=src python3 -m compileall -q src tests
git diff --check
```

Optional development tools, when installed:

```bash
ruff check src tests
mypy src
```

Generate a release-evidence snapshot with:

```bash
PYTHONPATH=src python3 scripts/run_release_gate.py \
  --output /tmp/elly-m7-evidence.json \
  --hardware-status pass
```

Only pass `--hardware-status pass` when the separately approved qwen3:8b hardware
evidence is in scope. The command is expected to return a nonzero release result
while quality or owner-UAT gates remain pending.

## Known limitations and open gates

- No complete 30-case live-provider quality/scoring corpus has been approved.
- Owner UC-01…UC-12 UAT is pending.
- Claim-level `known` research answers depend on the hosted provider supplying
  cited passages; URL metadata alone remains `inferred` or `unknown`.
- Current market research is intentionally conservative and may abstain when a
  direct timely quote cannot be established.
- Cloud pricing uses a conservative configured reservation, not an automatically
  synchronized authoritative provider price feed.
- The backup cryptography boundary still needs a vetted production dependency and
  owner-approved recovery acceptance.
- Full page-body RAG, local page reading, semantic/vector memory, web UI, portable
  trace export, and autonomous tool execution are outside the current V1 scope.
- Elly is a prototype and should not be used as authoritative medical, legal, or
  financial advice.

## Repository map

```text
src/elly/domain/          contracts, state, validation, context resolution
src/elly/application/     conversation, research, specialist orchestration
src/elly/ports/           provider and persistence boundaries
src/elly/adapters/        Ollama, OpenAI, SQLite, audit adapters
src/elly/research/        freshness, citation validation, source selection
src/elly/specialists/     manifests, contracts, registry, fake provider
src/elly/presentation/    terminal CLI and rendering
config/specialists/       declarative specialist capability manifests
tests/                    deterministic stdlib unittest suite
scripts/                  smoke, benchmark, and release-evidence helpers
docs/                     requirements, design, plans, reports, and evidence
```

Start with [MILESTONE_PLAN.md](docs/MILESTONE_PLAN.md) for the roadmap and
[CONVERSATION_IMPROVEMENT_LOG.md](docs/CONVERSATION_IMPROVEMENT_LOG.md) for the
complete record of improvements made during verification and owner testing.

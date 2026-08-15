# Elly Project Guide

This guide describes the complete Elly project as implemented in the repository,
including the V1 baseline and the V1.5 iteration. It is based on the current
source code, tests, configuration, Git history, and project documentation.

The source code and executable tests are authoritative when they differ from
older milestone notes.

## 1. Executive summary

Elly is a terminal-first, local-first personal AI assistant. Ordinary
conversation uses a local Ollama generalist. When the owner explicitly enables
cloud mode, current-information research and selected specialist tasks may use
hosted OpenAI adapters under application-owned privacy, consent, cost, timeout,
cancellation, and audit controls.

The project is a Python modular monolith using ports and adapters. It currently
supports local Ollama conversation, context-aware multi-turn conversation,
hosted web research, independent HTTPS document retrieval for evidence
validation, coding and research-specialist capabilities, privacy classification,
exact one-use consent, SQLite sessions/profiles/traces/source metadata,
idempotency, cancellation, redacted audit, provenance, guardrails, backup/restore,
and deterministic fake providers.

It is not yet a complete local document-ingestion or vector-RAG system. It does
not currently provide PDF/DOCX ingestion, chunking, embeddings, a vector
database, semantic search, or a local document corpus.

## 2. Current status

The latest repository commit is `2e97406`:

```text
feat(v1.5): add typed capabilities and resilient conversation workflows
```

V1.5 was closed by owner decision on 2026-08-07 for its implemented scope.
Live-provider verification remains explicitly deferred, and historical V1
release gaps remain separate.

The current deterministic suite passes **260 tests, 0 failures, 0 skipped**.
The verification documents also record passing compilation, Ruff, strict mypy,
and whitespace checks. Live Ollama/OpenAI behavior is a separate evidence
category and is not implied by the deterministic suite.

Authoritative orientation documents:

- [`README.md`](../README.md)
- [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md)
- [`v1.5/V1_5_CLOSURE.md`](v1.5/V1_5_CLOSURE.md)
- [`v1.5/V1_5_IMPLEMENTATION_VERIFICATION.md`](v1.5/V1_5_IMPLEMENTATION_VERIFICATION.md)
- [`v1.5/TECHNICAL_DESIGN.md`](v1.5/TECHNICAL_DESIGN.md)
- [`v1/V1_VERIFICATION_REPORT.md`](v1/V1_VERIFICATION_REPORT.md)

## 3. Repository map

| Area | Main files | Responsibility | Status |
|---|---|---|---|
| Entry point | [`src/elly/__main__.py`](../src/elly/__main__.py) | Loads environment/configuration and starts CLI | Essential |
| Composition | [`src/elly/composition.py`](../src/elly/composition.py) | Wires concrete adapters to ports | Essential |
| Presentation | [`src/elly/presentation/`](../src/elly/presentation/) | CLI commands, validation, rendering | Essential |
| Application | [`src/elly/application/`](../src/elly/application/) | Routing, use cases, capability dispatch, research, specialists | Essential |
| Domain | [`src/elly/domain/`](../src/elly/domain/) | Models, enums, errors, validation, state transitions | Essential |
| Ports | [`src/elly/ports/`](../src/elly/ports/) | Replaceable provider and infrastructure contracts | Essential |
| Adapters | [`src/elly/adapters/`](../src/elly/adapters/) | Ollama, OpenAI, HTTP retrieval, SQLite, audit, clock | Essential/optional |
| Research | [`src/elly/research/`](../src/elly/research/) | Freshness, source selection, citation and evidence policy | Optional |
| Specialists | [`src/elly/specialists/`](../src/elly/specialists/) | TOML manifests, contracts, registry, fakes | Optional |
| Guardrails | [`src/elly/guardrails/`](../src/elly/guardrails/) | Limits, retry, timeout, cost, circuit, executor | Essential |
| Memory/operations | [`src/elly/memory.py`](../src/elly/memory.py), [`operations.py`](../src/elly/operations.py) | Profile items, backup, restore | Optional |
| Evaluation | [`src/elly/evaluation/`](../src/elly/evaluation/) | Evaluation catalog and release evidence | Verification |
| Configuration | [`config.example.toml`](../config.example.toml), [`config.py`](../src/elly/config.py) | Runtime configuration | Essential |
| Tests | [`tests/`](../tests/) | Standard-library unit/integration tests | Essential |
| Documentation | [`docs/v1/`](v1/), [`docs/v1.5/`](v1.5/) | Requirements, design, decisions, verification | Project knowledge |

There are no REST API routes or web UI entry points. The primary interface is
the terminal REPL.

## 4. Startup and composition

```text
python -m elly
  -> elly.__main__.main()
  -> load_dotenv() and parse --config
  -> composition.build()
  -> load_config()
  -> open SQLite and apply migrations
  -> construct guardrails and bounded executor
  -> construct research and specialist providers
  -> construct Ollama or fake generalist
  -> construct capability registry
  -> construct ConversationOrchestrator
  -> run Cli
```

`composition.build()` is the composition root. It is the one place that knows
which concrete classes implement the ports. Application and domain code should
not import Ollama, OpenAI, or SQLite implementations directly.

## 5. Architecture

The closest architectural description is a ports-and-adapters modular monolith
with presentation, application, domain, port, and infrastructure boundaries.

```text
Presentation / CLI
        |
        v
Application workflows
        |
        +--> Domain models and policy
        +--> Ports
                 |
                 v
             Adapters
                 |
                 +--> Ollama / OpenAI / HTTPS / SQLite
```

The application owns deterministic sequencing and authorization. Models and
external providers return untrusted data; they do not control tools,
permissions, persistence, or external actions.

Important collaborators include `ConversationOrchestrator`, `RoutingPolicy`,
`ContextBuilder`, `LocalConversationUseCase`, `CapabilityRegistry`,
`CloudAuthorizationPolicy`, `CancellationToken`, and `GuardrailController`.
V1.5 extracted local execution, routing, context, authorization, capability
dispatch, and cancellation from the earlier larger orchestration path.

## 6. Ports and adapters

Ports are Python `Protocol` interfaces. Adapters satisfy them structurally by
providing the required methods.

| Port | Real implementation | Deterministic implementation |
|---|---|---|
| `GeneralistPort` | `OllamaGeneralist` | `FakeGeneralist` |
| `WebResearchProvider` | `OpenAIHostedWebSearch` | `FixtureWebResearchProvider` |
| `SpecialistProviderPort` | `OpenAISpecialistProvider` | `FakeSpecialistProvider` |
| `DocumentRetrievalPort` | `HttpDocumentRetriever` | Test doubles |
| `SessionRepositoryPort` | `SqliteSessionRepository` | In-memory SQLite/test repositories |
| `AuditPort` | `StructuredAuditLog` | In-memory audit doubles |
| `ClockPort` | `SystemClock` | `FixedClock` |
| `CostPort` | Guardrail cost ledger | Deterministic cost tests |

The contracts are in [`src/elly/ports/`](../src/elly/ports/); concrete wiring is
in [`composition.py`](../src/elly/composition.py). A remaining cleanup area is
the repository contract: newer M6/V1.5 operations are implemented by SQLite,
but not every operation is represented as cleanly in the original core protocol
as the session/message methods.

## 7. Local conversation workflow

```text
CLI input
  -> normalize_and_validate()
  -> TaskRequest
  -> ConversationOrchestrator.handle()
  -> load bounded recent history and resolve dependent context
  -> RoutingPolicy.decide()
  -> claim idempotency operation
  -> build prompt and context manifest
  -> persist user message if allowed
  -> LocalConversationUseCase.execute()
  -> guardrails and CancellationToken
  -> OllamaGeneralist.generate()
  -> validate model output
  -> persist assistant message
  -> record provenance and audit
  -> complete operation
  -> render TaskResult
```

The local path uses a configured model, bounded context, confirmed profile items
where permitted, output limits, request-scoped guardrails, and no cloud fallback.
Failures become typed blocked, failed, cancelled, partial, or completed
outcomes. If generation succeeds but assistant persistence or completion auditing
fails, Elly returns `PARTIAL` rather than claiming durable success.

## 8. Routing and capabilities

Routing is application-owned; the model does not decide whether a cloud call or
specialist should occur. Current routes include `LOCAL_GENERALIST`,
`WEB_RESEARCH`, `CODING_SPECIALIST`, and `RESEARCH_SPECIALIST`.

The `stock_analysis` manifest exists and is validated, but the deterministic
router does not currently expose stock-specialist execution. Current stock
questions use web research instead.

Capability descriptors identify the capability, route, request schema,
external-boundary requirement, consent requirement, destination, model, purpose,
and configured cost ceiling. Capabilities can be unavailable because they are
not configured, disabled, or their provider health check fails.

## 9. Hosted research workflow

```text
User question
  -> freshness/current-information detection
  -> WEB_RESEARCH route
  -> cloud-mode authorization
  -> privacy classification and exact consent when required
  -> OpenAI web_search
  -> citation validation and source selection
  -> freshness/evidence policy
  -> optional independent document retrieval
  -> ClaimSupport records
  -> known/inferred/unknown result
  -> source and provenance persistence
```

Restricted content is blocked. Unclassified content is blocked rather than
silently sent to a provider. Local or owner-specific content requires exact
one-use consent bound to payload, provider, model, purpose, categories, cost,
and expiry.

Safeguards include HTTPS/public-host validation, URL canonicalization, bounded
results/output, current-market source restrictions, injection quarantine,
conflict detection, and a bounded citation-repair retry.

## 10. Document retrieval and evidence validation

V1.5 added a real document-retrieval port and adapter:

- Port: [`document_retrieval.py`](../src/elly/ports/document_retrieval.py)
- Adapter: [`http_document_retriever.py`](../src/elly/adapters/http_document_retriever.py)
- Policy: [`evidence_policy.py`](../src/elly/research/evidence_policy.py)

The adapter provides HTTPS-only URLs, public DNS/IP checks, DNS-pinned peer
connections, redirect validation/limits, content-type validation, response-size
bounds, timeouts, typed network errors, SHA-256 content hashing, and cooperative
cancellation.

`EvidencePolicy` checks whether a candidate source actually contains the
supporting passage. A URL, provider snippet, or source metadata alone cannot
establish a `known` fact. If retrieval fails, the source can remain a lead while
the claim is downgraded to `unknown`, `inferred`, `partial`, or `blocked`.

This is not local document RAG: there is no user-facing import workflow,
document extraction, chunking, embedding generation, vector database, semantic
search, or local document corpus.

## 11. Specialists

Specialist manifests live in [`config/specialists/`](../config/specialists/).
They define capabilities, privacy, risk, timeouts, and exclusions. Provider,
model, and pricing choices remain centralized in the main configuration.

Specialist calls are structured and tool-free. The application validates scope,
manifest enablement, privacy, consent, output schema, output size, truncation,
and false claims of completed external actions. Specialists cannot execute tools,
write files, run shell commands, or perform high-impact actions.

## 12. Ollama integration

The real adapter is [`OllamaGeneralist`](../src/elly/adapters/ollama_generalist.py).
Defaults are `http://127.0.0.1:11434`, model `qwen3:8b`, streaming enabled,
thinking output disabled, a configured timeout, and Ollama `num_predict` output
limits. It calls `/api/tags` for health and `/api/generate` for generation.

Missing models, 5xx responses, malformed JSON, empty output, network failures,
timeouts, and cancellation become typed application errors.

`bind: address already in use` means another process already owns Ollama’s
listening address, usually port `11434`. Elly is a client and should connect to
the existing server rather than start another one.

```bash
ollama list
ollama ps
ss -ltnp | grep 11434
```

## 13. Configuration

Configuration precedence is:

```text
built-in defaults -> TOML file -> ELLY_* environment overrides
```

Provider/model choices are centralized in `[providers]` and `[models]`.
Limits, timeouts, retention, backup, research, specialists, logging, and
pricing are configured in their corresponding TOML sections. Secrets belong in
`.env` or the process environment, never TOML.

## 14. SQLite persistence and operations

The SQLite schema is version 3 and contains `sessions`, `messages`, `tasks`,
`profile_items`, `profile_tombstones`, `audit_events`, `task_sources`,
`task_operations`, and `task_provenance`.

The repository supports additive migrations and rollback on migration failure.
Features include normal sessions, no-store message bodies, confirmed profiles,
retention, durable task state, idempotency, source metadata, redacted audit
events, startup interruption reconciliation, health checks, and authenticated
prototype backup/restore.

The backup mechanism is explicitly prototype-grade. Vetted AEAD and key
management remain production requirements.

## 15. Privacy and trust boundaries

Important trust boundaries are user input, model output, hosted providers, source
URLs/page contents, and SQLite/backup files. All provider and model output is
treated as untrusted data.

The application enforces local-only default behavior, no silent cloud fallback,
restricted-data blocking, exact one-use consent, redacted audit events, no
specialist tools/actions, localhost-only Ollama, and safe URL retrieval.

## 16. Idempotency and cancellation

Before provider dispatch, the orchestrator claims an operation using a request
digest and capability ID. Repeated completed requests return a possible-duplicate
partial result instead of invoking the provider again. Retryable failures may be
claimed again; uncertain failures are not automatically replayed.

`CancellationToken` is shared across local Ollama generation, hosted research,
document retrieval, and specialist execution. Adapters register callbacks that
can close active connections. A cancelled operation never becomes a completed
success.

## 17. Testing and verification

```bash
PYTHONPATH=src python3 -W error::ResourceWarning \
  -m unittest discover -s tests -t .
PYTHONPATH=src python3 -m compileall -q src tests
git diff --check
```

Optional tools:

```bash
ruff check src tests
mypy src
```

Tests cover input/configuration, provider contracts, Ollama, routing,
capabilities, authorization, research, document retrieval, evidence policy,
SQLite/migrations, no-store behavior, profiles, retention, idempotency,
cancellation, specialists, guardrails, audit redaction, backups, and release
evidence.

The deterministic suite does not prove current live web quality, provider
billing accuracy, aggregate model quality, or owner acceptance of every CLI
workflow. Those require separate live-provider and UAT evidence.

## 18. Complete, partial, deferred, and unused areas

### Implemented and tested

- Local conversation
- Ports and concrete adapters
- SQLite persistence
- Typed routing and capabilities
- Privacy and consent
- Guardrails and cancellation
- Evidence validation
- Independent document retrieval
- Idempotency and migrations
- Specialist contracts and manifests
- Deterministic verification

### Implemented but evidence is partial

- Live Ollama beyond bounded smoke tests
- Live OpenAI research and specialist quality
- Aggregate routing/evidence-quality thresholds
- Owner UAT for UC-01 through UC-12
- Authoritative provider pricing/accounting

### Deferred

- Local document ingestion
- Vector/semantic memory
- Full local page-body RAG
- Web UI, voice, vision, crawling, and computer control
- Autonomous tools and parallel/recursive specialist graphs
- Finance-specialist execution and portable trace export

### Present but not currently exposed as a route

- `stock_analysis` specialist manifest

## 19. Interview preparation

Be ready to explain:

1. Why `composition.build()` is the composition root.
2. How Python `Protocol` interfaces enable structural provider substitution.
3. Why the application, rather than the model, owns routing and authorization.
4. How request-scoped guardrails protect nested workflows.
5. Why task status and epistemic status are separate axes.
6. How consent is bound to a payload and provider call.
7. How retrieval prevents a URL or snippet from becoming unsupported fact.
8. How DNS pinning and redirect checks protect the retrieval boundary.
9. How idempotency prevents repeated provider dispatch.
10. How cancellation propagates into active connections.
11. Why persistence/audit failure produces `PARTIAL` rather than false success.
12. Why the project is not yet a vector-RAG system.
13. Which claims are proved by deterministic tests versus live evidence.

A concise interview description is:

> Elly is a terminal-first ports-and-adapters modular monolith. It keeps
> orchestration, routing, authorization, privacy, persistence, and uncertainty
> decisions in the application. Local conversation uses Ollama, hosted research
> uses OpenAI search, and candidate sources can be independently retrieved and
> validated through a typed HTTPS document-retrieval port. The system has
> claim-level evidence and provenance, but local document ingestion, embeddings,
> and vector search remain deferred.

## 20. Recommended next improvements

1. Complete aggregate live-quality and owner-UAT evidence.
2. Replace the prototype backup envelope with vetted AEAD/key management.
3. Formalize authoritative provider pricing and actual cost reconciliation.
4. Expand repository protocols so all M6/V1.5 operations are explicitly typed.
5. Reduce remaining coordination responsibility in `ConversationOrchestrator`.
6. If local RAG is a goal, add ingestion, extraction, chunking, embeddings,
   vector storage, retrieval, and document-level citation models as a separate
   versioned capability.


# Elly V1.5 Technical Design

**Status:** Approved, implemented, and closed by owner decision on 2026-08-07.

Closure evidence and the explicitly deferred live-provider exception are recorded
in [V1_5_CLOSURE.md](V1_5_CLOSURE.md).

## 1. Proposed approach

V1.5 should retain the modular monolith and `ConversationOrchestrator`, but reduce the orchestrator to a small, explicit coordinator. It will validate a request, create or resume a task, obtain a deterministic route decision, select an available workflow, execute it, finalize durable records, and return a typed result.

Independent policy and external-boundary work moves to small collaborators only where it is independently testable or changes for different reasons:

| Concern | Proposed responsibility |
| --- | --- |
| Route proposal and final route | `RoutingPolicy` |
| Context construction | Existing context functions behind a `ContextBuilder` port/class if extraction is needed |
| Payload classification | `PrivacyPolicy` |
| External-transmission permission | `CloudAuthorizationPolicy` |
| Optional feature lookup/dispatch | `CapabilityRegistry` |
| Local conversation | `LocalConversationUseCase` |
| Research | `ResearchUseCase` (evolving the current `ResearchPipeline`) |
| Specialists and future tools | Capability handlers, each with precise internal types |
| Result assembly | Existing response composer, extended for outcome/provenance rules |
| Persistence/audit completion | A narrow application `UnitOfWork`/completion service over the existing repository and audit ports |

This is intentionally not a framework or a generic workflow engine. Local conversation remains a direct required workflow. Research and specialists become optional executable capabilities because they can be unavailable and are expected to grow.

### Target request flow

```text
CLI -> validated TaskRequest -> ConversationOrchestrator
    -> ContextBuilder
    -> RoutingPolicy (proposal + deterministic decision/reason code)
    -> CapabilityRegistry availability lookup, where applicable
    -> PrivacyPolicy classification
    -> CloudAuthorizationPolicy decision
    -> selected use case/capability
    -> ResponseComposer + provenance
    -> UnitOfWork finalization (task/result/evidence/audit)
    -> ConversationOutcome
```

No model proposal, descriptor, or provider response bypasses deterministic route, schema, availability, privacy, consent, or evidence checks.

## 2. Components and files

The following is the smallest expected change set. Names are proposed internal names, not new public API commitments.

| Area | Existing files to change | Proposed additions | Purpose |
| --- | --- | --- | --- |
| Workflow coordination | `src/elly/application/conversation.py`, `response_composer.py` | `routing.py`, `local_conversation.py`, optionally `context_builder.py` | Thin orchestrator and testable policies/use cases |
| Optional capabilities | `src/elly/specialists/registry.py`, `application/specialists.py` | `application/capabilities.py` | Typed descriptor, status, registry, and handler contract |
| Privacy | `src/elly/privacy.py` | optionally `application/authorization.py` | Separate classification from cloud authorization |
| Research/evidence | `src/elly/application/research.py`, `research/citation_validator.py`, `ports/web_research.py`, `adapters/openai_web_research.py` | `ports/document_retrieval.py`, `research/evidence_policy.py` | Retrieved claim-level evidence, eligibility, conflicts/freshness |
| Domain contracts | `src/elly/domain/models.py`, `enums.py`, `errors.py`, `state_machine.py` | none required initially | Typed route, capability, authorization, evidence, outcome, and provenance models |
| Persistence | `src/elly/ports/repository.py`, `adapters/sqlite_repository.py`, `ports/audit.py`, `adapters/audit_log.py` | `application/unit_of_work.py` if a dedicated class proves clearer | Additive migrations, atomic local completion where possible, explicit degraded outcomes |
| Composition/configuration | `src/elly/composition.py`, `config.py`, `pyproject.toml` | none required | Required-dependency and capability validation; strict static analysis |
| CLI/rendering | `src/elly/presentation/cli.py`, `render.py` | none required | Display typed statuses/provenance; typed cancellation handling |
| Tests | Relevant existing test modules | `test_routing_policy.py`, `test_capabilities.py`, `test_authorization.py`, `test_evidence_policy.py`, `test_migrations_v15.py` | Unit, contract, integration, and legacy migration coverage |

The current `SpecialistRegistry` should either be replaced by, or adapted behind, the new capability registry. It should not coexist as a second general-purpose dispatch mechanism.

## 3. Contract, model, state, and data-flow changes

### Required dependencies and optional capabilities

Required services stay visible in constructor signatures and are validated during `build()`:

- clock, repository, audit sink, response composer, routing policy, privacy policy, cloud authorization policy, context builder, and local conversation use case;
- the provider port required for the configured local generalist.

Optional executable capabilities are registered at composition time through a typed common contract. A minimal contract should expose:

- `CapabilityDescriptor`: stable ID, display/route metadata, typed request type identifier, external-boundary and consent requirements;
- `CapabilityStatus`: available/unavailable plus a safe reason code;
- `can_handle(RouteRequest) -> CapabilityMatch` or schema validation equivalent;
- `execute(CapabilityRequest, ExecutionContext) -> TaskResult`.

The common contract is deliberately narrow. A research handler keeps its typed `SearchProvider` and document-retrieval ports; a calendar handler would use typed calendar requests and provider types. Do not introduce `execute(dict) -> dict`.

`CapabilityRegistry` only registers and returns dispatchable optional handlers. It rejects duplicate IDs, reports unavailable configured capabilities, and must never provide repositories, policies, loggers, or other required services.

### Routing

Add typed `RouteRequest`, `RouteProposal`, and `RouteDecision` models. Current deterministic keyword/freshness rules move out of `ConversationOrchestrator` unchanged initially, preserving V1 routes. `RouteDecision` includes a public reason code, such as `CURRENT_INFORMATION_REQUIRED`, `LOCAL_DEFAULT`, `CAPABILITY_UNAVAILABLE`, or `AUTHORIZATION_DENIED`.

Later, a model/classifier can submit a `RouteProposal` referencing a descriptor ID, but `RoutingPolicy` validates registration, handler availability, request schema, privacy result, consent/authorization requirements, and fallback rules before it selects the route. It stores no hidden reasoning.

### Privacy and cloud authorization

Keep the conservative current classifier, but make its output an explicit `ClassificationDecision` rather than using it as permission.

`CloudAuthorizationPolicy.authorize(...) -> AuthorizationDecision` accepts:

- classification;
- destination provider and model/service;
- payload digest and declared scope/category (not the payload for auditing);
- requested capability and external effect level;
- cloud mode and exact consent grant;
- capability availability.

The policy denies ambiguous/unclassified/restricted content, unavailable capabilities, local-only mode, missing/expired/wrong-provider/wrong-scope consent, and unknown destinations. Existing `ConsentWorkflow` remains the one-time exact-consent mechanism; authorization calls it rather than each workflow doing so independently.

For compatibility, retain existing persisted privacy values initially. Introduce canonical V1.5 names only with an explicit mapping, for example `REMOTE_ALLOWED -> PUBLIC`, `LOCAL -> OWNER_SPECIFIC`, and `RESTRICTED -> PRIVATE`. Do not silently reinterpret historical audit data.

### Claim-level evidence

Extend the current `EvidenceObject` into a structured immutable evidence record with, at minimum:

- evidence ID, canonical source ID/URL, title, publisher, retrieval time, source class, freshness, validation state, and optional content hash;
- supporting passage or structured source content;
- retrieval/validation metadata and safe failure reason;
- links to one or more `ClaimRecord`s.

`ClaimRecord` replaces rendered strings as the internal representation: claim ID, normalized/display text, support status (`supported`, `unsupported`, `conflicted`, `unverified`), and evidence IDs. Existing `ClaimSupport` can be evolved rather than duplicated.

Add a typed `DocumentRetrievalPort` for safely fetching a candidate source. Hosted search remains a discovery provider. A claim can be `known` only when the evidence policy sees a retrieved, validated supporting passage for that claim. If retrieval is disallowed, inaccessible, stale for a current claim, or inconclusive, retain candidate links as leads but return `UNKNOWN`, `PARTIAL`, or `BLOCKED` as appropriate; never promote snippets to known facts.

The initial evidence policy should be deterministic and conservative:

- validate URL and retrieval safety;
- retrieve content under timeout/cancellation controls;
- extract/retain a bounded supporting passage and hash;
- validate passage-to-claim linkage;
- detect conflicting claim records and preserve them;
- apply claim-type-specific freshness rules.

### Outcomes, finalization, retries, and cancellation

Keep the existing three-axis `TaskResult`, but make outcome mapping precise:

| Condition | Task status | Epistemic status |
| --- | --- | --- |
| Complete answer with sufficient evidence | `COMPLETED` | `KNOWN` or `INFERRED` |
| Valid useful result with incomplete persistence/evidence | `PARTIAL` | `INFERRED` or `UNKNOWN` |
| Policy/authorization denial | `BLOCKED` | `BLOCKED` |
| Evidence insufficient | `COMPLETED` or `PARTIAL` | `UNKNOWN` |
| Required optional capability absent | `FAILED` or `BLOCKED` with a typed `UNAVAILABLE` result reason | `UNKNOWN`/`BLOCKED` |
| Execution failure | `FAILED` | `UNKNOWN`/`BLOCKED` |
| Cancellation | `CANCELLED` | `BLOCKED` |

The requirements name `UNAVAILABLE` and `UNKNOWN` as statuses but the current model distinguishes task and epistemic status. The simplest compatible design is to add an `OutcomeCode`/reason-code enum on `TaskResult` (including `UNAVAILABLE` and `UNKNOWN`) rather than overload `TaskStatus`; this requires confirming the intended external API. `TaskStatus.FAILED` should become reachable rather than mapping all operational errors to `BLOCKED`.

Use a task/request ID as the idempotency key. Persist operation records before or around external calls, including capability ID, request digest, attempt number, and provider idempotency key where supported. On retry, reuse the record and do not append duplicate messages/evidence/audit completion events. When a provider cannot guarantee idempotency, return/audit a safe `POSSIBLE_DUPLICATE_EXECUTION` reason code.

Introduce a narrow completion service/unit of work for local durable operations: persist result metadata, messages, evidence references, task status, and audit intent with a defined order. SQLite can atomically commit its own tables; an audit sink outside that transaction needs an outbox-style pending audit record or a surfaced partial/failure result. Do not claim atomicity across an external provider call and SQLite.

Cancellation uses an `ExecutionContext`/cancellation token carried into use cases and provider ports. Once cancelled, no new external call starts; supported calls are cancelled; already validated evidence may persist; task becomes `CANCELLED`; partial text is kept only as `partial_work`, never as a completed answer.

## 4. Integration with V1

The first refactor should preserve the public CLI commands, `TaskRequest`, `ConversationOutcome`, local-generalist behavior, current specialist manifests, consent approval flow, SQLite data, and existing route keywords.

Integration should be incremental:

1. Extract existing logic verbatim behind policies/use cases and delegate from the orchestrator.
2. Adapt current research and specialist paths as the first registered optional handlers.
3. Keep existing ports/adapters where their contract is already typed; add narrowly scoped ports only for new evidence retrieval/cancellation needs.
4. Leave presentation as a consumer of `TaskResult`; add new display fields without changing existing output unless an outcome requires clarification.
5. Turn current reflective calls into port methods only after every implementation and test double supports the method.

This preserves the current modular-monolith structure and avoids a broad rewrite.

## 5. Edge cases and error handling

- **Route selects disabled capability:** deterministic routing returns a decision with `CAPABILITY_UNAVAILABLE`; do not invoke a provider or ask for consent.
- **Unregistered or schema-invalid model proposal:** reject it; fall back to deterministic local/research rules only where permitted.
- **Unclassified payload:** deny all external transmission before creating a provider request.
- **Consent mismatch/replay:** deny when payload digest, provider, model, capability, scope, cost, expiry, or one-time approval does not match.
- **Search finds a page but retrieval fails:** retain safe candidate metadata as a lead; mark affected claims unverified/unknown and never known.
- **Retrieved page lacks supporting passage:** evidence is ineligible for the claim; no known result.
- **Conflicting or stale sources:** retain competing claims/evidence and render the conflict; current-value claims cannot rely on stale evidence.
- **Answer generation succeeds, assistant persistence fails:** return a typed `PARTIAL`/`FAILED` result per the confirmed policy, surface the failure, and do not claim durable completion.
- **Audit write fails:** prevent high-impact/cloud dispatch if the prerequisite audit cannot be recorded; after execution, surface a non-silent partial/failure outcome and retain a retryable outbox record if implemented.
- **Retry after timeout:** use the persisted operation key; do not create duplicate message/evidence records; disclose possible duplicate external execution where unavoidable.
- **Cancellation during retrieval:** stop new fetches, cancel supported work, retain only validated evidence already completed, persist cancelled state, and do not compose an answer as complete.
- **Sensitive failures/logging:** redact before the sink; audit only IDs, classifications, hashes, safe reason codes, provider/capability IDs, and bounded operational metadata.

## 6. Compatibility and migrations

- Make schema changes additive in a new migration version. Do not rewrite V1/V2 migrations.
- Preserve existing sessions, messages, tasks, sources, and audit records as readable records.
- Add tables/columns for capability operation/idempotency records, evidence records, claim records/link tables, provenance references, and audit outbox state only if required by the final transaction design.
- Treat existing `task_sources` as historical source metadata. Do not upgrade it retroactively to claim-level evidence.
- Preserve existing task and privacy enum values; map them at read/use boundaries. Add new values only after verifying older readers tolerate them, or store V1.5-specific outcome/reason fields separately.
- Add a migration fixture representing an actual V1 schema/version-2 database and assert that it opens, migrates, retains content, and can process a new task.
- The in-memory consent store is compatible with V1 but not restart-durable. Keep it in V1.5 unless durable approvals are explicitly required; persistent consent expands the privacy/security scope significantly.

## 7. Test design

Keep existing V1 tests as regression coverage and add the following.

### Unit tests

- Routing decisions/reason codes, current V1 keywords, availability-aware fallback, untrusted route proposals.
- Classification and cloud authorization independently, including unclassified, wrong provider/scope, expiration, model/cost mismatch, and unavailable capability.
- Capability registry registration, duplicate ID rejection, availability statuses, typed unavailable result, and rejection of core-service lookup.
- Evidence eligibility using deterministic fixtures: metadata-only snippets, inaccessible pages, no supporting passage, stale source, duplicate/unsafe URL, conflict, valid claim-to-passage mapping.
- Outcome mapping, response provenance, failure taxonomy, redaction, and config/composition validation.

### Contract and integration tests

- Shared optional-capability contract suite for research, coding specialist, and a test-only new capability added without modifying the orchestrator or registry.
- Provider-port contract tests for input validation, normalized results, timeout/cancellation, error translation, and provider-detail containment.
- Orchestrator integration: availability checked before dispatch; authorization before cloud calls; persisted idempotency prevents duplicate calls/turns/evidence; cancellation behavior; audit/persistence failure outcomes.
- SQLite migration test from representative V1 data and tests for atomic local completion/outbox recovery if adopted.
- Limited live release tests for the configured model/search/retrieval path, only with public test data.

Enable a strict type-checking target for `src/elly/application`, `domain`, `ports`, and adapter interfaces first, then expand it to the full project. New code should not introduce untyped dependencies or `getattr()` capability discovery.

## 8. Risks, tradeoffs, and alternatives

| Decision | Benefit | Cost/risk |
| --- | --- | --- |
| Thin orchestrator plus a few policies/use cases | Separates independently testable policy without losing one readable lifecycle | Constructor/composition changes touch many tests |
| Typed optional-capability registry | Adding specialists no longer changes the orchestrator | Requires carefully bounded common contract; must not become a service locator |
| Independent document retrieval | Meets claim-level evidence requirement robustly | Adds network safety, parsing, timeout, and retention complexity |
| `OutcomeCode` in addition to existing statuses | Meets new vocabulary without breaking the three-axis model | Requires a decision on public rendering/API shape |
| SQLite outbox for audit reliability | Makes audit failures recoverable and observable | More schema/state complexity; avoid if a single durable audit sink can share the DB transaction |
| Persisted idempotency records | Prevents local duplication on retries | Cannot guarantee an external provider did not run without provider support |

The main alternative is to use the existing specialist manifest registry as the sole extensibility system. That is insufficient: it lacks typed execution, availability, descriptor, request-schema, and result contracts, and would force research to remain a special orchestrator branch. A small general optional-capability registry is justified; a generic plugin framework is not.

Another alternative is to accept provider-returned cited passages as evidence without independent retrieval. It is simpler, but does not fully meet the requirement that snippets/metadata cannot establish substantive claims. Treat hosted output as discovery unless it contains retrievable, validateable claim-level evidence.

## Recommended implementation order

1. Freeze V1 regression behavior with the existing suite; add characterization tests for routes, outcomes, consent, and persistence ordering.
2. Add strict typing configuration and typed constructor/composition validation; replace reflective discovery for required dependencies with explicit ports.
3. Define domain/application contracts for route decisions, capability descriptors/status/results, authorization decisions, outcome codes, and provenance.
4. Introduce `CapabilityRegistry`; adapt research and specialists as registered optional capabilities; prove a test capability can be added without changing the orchestrator.
5. Extract current deterministic routing and context behavior into `RoutingPolicy`/context collaborator, retaining V1 rules and adding reason codes.
6. Split privacy classification from cloud authorization; route all remote execution through the authorization policy and add fail-closed tests.
7. Extract local, research, and specialist workflows from the orchestrator; leave it as coordinator and response finalizer.
8. Add claim/evidence models, safe document retrieval, evidence eligibility policy, conflict/freshness handling, and claim-level response composition.
9. Define outcome mapping, idempotency records, cancellation propagation, and persistence/audit finalization semantics; implement an outbox only if the final audit topology requires it.
10. Add V1.5 SQLite migrations and representative V1 migration tests; then run unit, contract, integration, and limited public-data live verification.

# Elly V1.5 Improvement Proposal

**Document status:** Proposed 
**Target release:** V1.5 
**Project name:** Elly 
**Change type:** Incremental architectural and reliability improvements 
**Depends on:** Elly V1

---

## 1. Purpose

Elly V1.5 is a focused improvement release built on the completed V1 implementation. It improves architectural maintainability, type safety, privacy enforcement, research evidence quality, failure handling, and the testability of deterministic decisions.

V1.5 is not a redesign and does not introduce a large set of new user-facing features. Existing V1 behavior should remain compatible unless a change is required to correct unsafe, ambiguous, or unreliable behavior.


## 2. V1.5 Goals

1. Reduce the responsibilities owned directly by `ConversationOrchestrator`.
2. Replace implicit optional behavior and reflective `getattr()` calls with explicit typed contracts while keeping optional capabilities easy to extend.
3. Clarify the boundaries between domain concepts, application policy, infrastructure, and interfaces.
4. Enforce separate privacy-classification and cloud-authorization decisions.
5. Require claim-level evidence before externally sourced claims can be classified as `known`.
6. Improve capability validation, retries, cancellation, persistence behavior, and failure reporting.
7. Preserve V1 functionality and stored data unless an intentional change is documented.

## 3. Non-Goals

Elly V1.5 will not:

- Replace the modular monolith with microservices.
- Introduce a graphical or web interface.
- Allow language models to authorize or invoke tools independently.
- Replace SQLite solely for scalability.
- Redesign the entire conversation workflow.
- Require every small responsibility to become a separate class.
- Introduce arbitrary source-code size limits.
- Add unrelated product features.

## 4. Architectural Principles

### 4.1 Application-owned authority

Language models may propose routes, research queries, specialist selection, candidate claims, and response content. They must not authorize cloud transmission, private-data disclosure, tool execution, evidence classification, or final epistemic status. Those decisions remain in deterministic application code.

### 4.2 Explicit contracts

Dependencies and capabilities must be represented through typed, documented interfaces. Core behavior must not discover required capabilities through `getattr()`, caught `AttributeError`, untyped dependency dictionaries, generic service locators, or silent `None` defaults.

### 4.3 Fail-closed safety

When Elly cannot determine whether an external action is permitted, it must deny or block the action. This applies to unclassified payloads, missing or inadequate consent, unavailable cloud capabilities, invalid provider configuration, and evidence that cannot be retrieved or validated.

### 4.4 Evidence before certainty

Search-result metadata and snippets may help discover sources, but they are not sufficient evidence for substantive factual claims. An external factual claim may be classified as `known` only when eligible evidence supports that claim.

### 4.5 Incremental refactoring

V1.5 should improve the current implementation without replacing working components unnecessarily. A responsibility should be separated when it contains independently changing policy, crosses an external boundary, requires independent testing, or has meaningful failure behavior.

## 5. Improvement Area 1: Conversation Orchestration

### 5.1 Current concern

`ConversationOrchestrator` currently coordinates or directly owns routing, context construction, persistence sequencing, research policy, specialist execution, auditing, privacy-related decisions, and result composition. This concentration makes it harder to test, understand, and modify safely.

### 5.2 Decision

Elly shall retain a high-level `ConversationOrchestrator`, but its primary responsibility shall be workflow coordination:

1. Receive a validated request.
2. Create or resume the task.
3. Request a routing decision.
4. Select the applicable workflow.
5. Execute the selected workflow.
6. Finalize and return the result.

The orchestrator should delegate specialized policy and mechanisms to explicit collaborators.

| Responsibility | Recommended abstraction |
|---|---|
| Routing decisions | `RoutingPolicy` |
| Context construction | `ContextBuilder` |
| Payload classification | `PrivacyPolicy` |
| Cloud authorization | `CloudAuthorizationPolicy` |
| Local-answer workflow | `LocalConversationUseCase` |
| Research workflow | `ResearchUseCase` |
| Specialist workflow | `SpecialistUseCase` |
| Optional capability discovery and dispatch | `CapabilityRegistry` |
| Persistence transaction | `UnitOfWork` |
| Audit recording | `AuditSink` |
| Final result composition | `ResponseComposer` |

These names are architectural recommendations, not mandatory public API names.

The orchestrator may choose which workflow runs, but it should not implement privacy classification, evidence eligibility, search-result interpretation, provider-specific requests, database operations, or CLI formatting.

### 5.3 Acceptance criteria

- Routing policy can be tested without a model, database, CLI, or network service.
- Privacy authorization can be tested without a model or external provider.
- Research evidence eligibility can be tested with deterministic fixtures.
- Provider adapters can be replaced without rewriting orchestration logic.
- Existing V1 routes continue to behave consistently.
- The orchestrator does not import concrete OpenAI, Ollama, SQLite, HTTP, or CLI implementations.

### 5.4 Rationale

A central coordinator remains useful because a request has one lifecycle. Removing the orchestrator entirely would scatter sequencing across handlers. Keeping it thin preserves a readable workflow while allowing independently changing policies and external mechanisms to evolve and be tested separately.

## 6. Improvement Area 2: Typed Capability Contracts

### 6.1 Current concern

Optional collaborators and reflective `getattr()` calls weaken static type checking and defer configuration errors until uncommon execution paths run.

### 6.2 Decision

Every collaborator shall be classified as either a required dependency or an explicitly optional capability.

Required dependencies must be supplied during application composition, implement a defined interface, be validated at startup, and cause a clear startup failure when missing or incompatible.

Optional capabilities must expose an explicit availability state, use a typed interface, return a defined unavailable result when disabled, and be visible to routing before a dependent route is selected.

Python `Protocol` definitions or abstract base classes may define ports. Typed request and result objects should be used at application boundaries, including concepts such as `RouteRequest`, `RouteDecision`, `ResearchRequest`, `ResearchResult`, `EvidenceRecord`, `AuthorizationDecision`, `CapabilityStatus`, `UnavailableCapability`, and `TaskResult`.

Strict static analysis should be enabled with `mypy`, `pyright`, or an equivalent checker.

### 6.3 Required core services versus optional capabilities

Elly shall not treat every dependency as a registry entry. The implementation must distinguish between two categories:

| Component category | Examples | How it is supplied |
|---|---|---|
| Required core service or policy | Routing policy, privacy policy, conversation repository, response composer | Explicit constructor dependency validated at startup |
| Optional executable capability | Research, specialist, calendar, email, document analysis | Typed capability handler registered during application composition |

Required core services must remain visible in constructor signatures. They must not be retrieved from a generic registry because doing so would hide essential dependencies and turn the registry into a service locator.

Optional executable capabilities should share a stable application-level contract. Conceptually, each handler should provide:

- A stable capability identifier.
- A typed descriptor explaining what the capability does.
- An availability status and reason when unavailable.
- A way to determine whether it can handle a request.
- A typed execution entry point that returns a `TaskResult` or another defined result type.

The exact interface name is not mandatory, but a design similar to `CapabilityHandler` is recommended.

### 6.4 Typed capability registry

A `CapabilityRegistry` should contain only dispatchable optional capabilities. The orchestrator may ask the registry for a handler selected by routing, but arbitrary application code must not use it to obtain databases, loggers, privacy policies, repositories, or other required services.

In practical terms, this means the central workflow depends on one stable registry instead of gaining a new constructor argument and `if` branch every time an optional feature is added.

Adding a conforming optional capability should normally require only:

1. Implementing the capability handler.
2. Defining capability-specific configuration.
3. Registering the handler in the application composition root.
4. Defining its privacy, authorization, and routing metadata or policy.
5. Adding contract and behavior tests.

It should not require changes to `ConversationOrchestrator`, `CapabilityRegistry`, existing capability handlers, or existing provider adapters.

This is an extensibility goal, not a requirement to make every operation generic. A broad interface such as `execute(data: dict) -> dict` should be avoided because it hides input requirements, output meaning, errors, privacy needs, and external effects.

Elly should instead use two levels of typing:

1. **Common application contract:** A stable handler interface supports registration, availability checks, and dispatch.
2. **Capability-specific contracts:** Each capability uses precise internal request, result, provider, and error types. For example, research may depend on a typed `SearchProvider`, while calendar management may depend on a typed `CalendarProvider`.

### 6.5 Routing newly registered capabilities

Registration alone does not determine when a capability should run. Elly should use a hybrid routing model:

- Core workflows such as local conversation and research may use explicit deterministic routing rules.
- Additional optional capabilities may publish typed descriptors that a model or classifier can use to propose a capability.
- A model-generated proposal is never authorization to execute.
- Deterministic application policy must verify registration, availability, request-schema validity, privacy classification, consent, destination, and other authorization conditions before dispatch.

This approach allows new capabilities to participate in routing without adding a new orchestrator branch for each one, while preserving application-owned authority.

### 6.6 Example extension path

If a future calendar capability is added, Elly should be able to integrate it by implementing and registering a `CalendarCapability`, configuring its provider adapter, declaring its descriptor and authorization needs, and adding tests. The central orchestrator and existing research or specialist implementations should remain unchanged.

### 6.7 Acceptance criteria

- No required V1.5 collaborator is detected through `getattr()`.
- Missing required dependencies produce a clear startup error.
- Disabled optional capabilities return a typed unavailable result.
- Routing cannot select a workflow whose required capability is unavailable.
- Static type checking covers application services and provider ports.
- Tests verify that incompatible implementations are rejected during composition or validation.
- A test capability can be implemented and registered without modifying `ConversationOrchestrator`, `CapabilityRegistry`, or existing capability handlers.
- Required core services are explicit constructor dependencies and cannot be retrieved from the optional capability registry.
- Registered capabilities expose a stable identifier, typed descriptor, availability state, and typed execution contract.
- Capability-specific provider interfaces remain strongly typed rather than accepting and returning unstructured dictionaries.
- A descriptor-based route proposal cannot bypass deterministic privacy, consent, availability, or input-validation checks.

### 6.8 Rationale

Explicit ports make capability absence a normal, visible application state instead of a late runtime surprise. The typed registry keeps optional features extensible without hiding required dependencies or weakening capability-specific contracts. This improves editor support, static analysis, startup diagnostics, test construction, provider replaceability, and the cost of adding future features.

## 7. Improvement Area 3: Application and Domain Boundaries

### 7.1 Decision

| Layer | Responsibilities |
|---|---|
| Domain/Core | Task state, epistemic status, evidence, claims, consent grants, and provider-independent value objects |
| Application | Workflows, routing policy, privacy authorization, evidence eligibility, and capability coordination |
| Infrastructure | Ollama, OpenAI, search, HTTP retrieval, SQLite, filesystem, clock, and provider adapters |
| Interface | CLI input, command parsing, progress presentation, and user-facing formatting |

Dependencies must point inward:

- Interface code may depend on application contracts.
- Infrastructure adapters may implement application ports.
- Application policy may depend on domain concepts and provider-independent interfaces.
- Domain code must not depend on OpenAI, Ollama, SQLite, HTTP, or CLI implementations.

### 7.2 Routing policy

A model may produce a route proposal, but deterministic application policy makes the final decision. It may consider user intent, freshness needs, capability availability, privacy classification, consent, previous failures, and allowed fallbacks.

For optional extensions, routing may inspect registered capability descriptors so that adding a handler does not require adding a new branch to the orchestrator. Descriptors are routing inputs only; they do not grant permission or guarantee execution.

A route decision should include a concise diagnostic reason code. It must not store or expose hidden model reasoning or chain-of-thought.

### 7.3 Acceptance criteria

- Domain modules do not import infrastructure or interface modules.
- Application workflows depend on ports rather than concrete providers.
- Model-generated route proposals are treated as untrusted input.
- Deterministic policy makes the final routing decision.
- Route decisions contain a documented reason code.
- Replacing a provider does not require changing application workflows.

### 7.4 Rationale

Routing and privacy are application policies because they govern how Elly uses capabilities; they are neither provider mechanisms nor pure business entities. This boundary keeps core concepts provider-independent without forcing every rule into the domain layer for stylistic purity.

## 8. Improvement Area 4: Privacy Classification and Authorization

### 8.1 Decision

Elly shall make two separate decisions:

1. **Classification:** What kind of data does the payload contain?
2. **Authorization:** May that classified payload cross the requested boundary?

Suggested classifications are `PUBLIC`, `OWNER_SPECIFIC`, `PRIVATE`, and `UNCLASSIFIED`. A classification never grants authorization by itself.

Cloud authorization should consider payload classification, destination provider, exact payload or category, consent and its scope, consent expiration, operating mode, and requested capability.

Transmission must be denied when classification is missing or `UNCLASSIFIED`, required consent is missing or inadequate, the provider capability is unavailable, or policy returns an ambiguous result.

Models may help identify sensitive content, but their output must not be the sole authorization mechanism.

### 8.2 Acceptance criteria

- Classification and cloud authorization are separate operations.
- No classification automatically grants permission.
- `UNCLASSIFIED` payloads cannot be transmitted externally.
- Missing or expired consent prevents cloud transmission.
- Consent for one provider does not authorize another provider.
- Consent for one payload scope does not authorize unrelated private content.
- Decisions are auditable without retaining unnecessary sensitive payloads.
- Privacy tests require no external model or network calls.

### 8.3 Rationale

Separating “what is this data?” from “may it leave this boundary?” prevents classification from accidentally becoming permission. Failing closed protects the system when configuration, consent, or classification is incomplete.

## 9. Improvement Area 5: Claim-Level Research Evidence

### 9.1 Decision

An externally sourced material claim may be classified as `known` only when it is connected to eligible claim-level evidence:

```text
Claim
  -> Supporting passage
  -> Retrieved document
  -> Canonical source
  -> Retrieval and validation metadata
```

An eligible evidence record should contain:

- A supporting passage or structured source content.
- A canonical URL or stable source identifier.
- Source title and publisher or origin.
- Retrieval timestamp.
- Claim-support relationship.
- Validation status.
- Content hash when appropriate.
- Relevant freshness metadata for time-sensitive claims.

Search titles, URLs, summaries, and snippets may discover and rank candidate sources or report that a result appeared. They must not independently support substantive claims about the page's subject.

When a relevant page cannot be retrieved or validated, Elly should mark the affected claim `unknown`, `blocked`, or otherwise unverified; explain the limitation; optionally provide candidate links as leads; and avoid presenting snippets or citations as verified support.

A hosted research provider may support a `known` result only when it returns identifiable claim-level evidence that Elly can validate and that actually supports the associated claim. Otherwise, it is a discovery, query-planning, inference, or research-lead source.

### 9.2 Acceptance criteria

- Every material external claim marked `known` references eligible evidence.
- A search snippet alone cannot produce a `known` substantive claim.
- Inaccessible sources produce an explicit unverified or blocked result.
- Citations are attached to the claims they support.
- Unsupported claims are downgraded before final composition.
- Conflicting evidence is represented rather than silently resolved.
- Time-sensitive claims include sufficient freshness information.
- Tests cover misleading snippets, inaccessible pages, stale content, conflicting sources, and incomplete citations.

### 9.3 Rationale

Search metadata is optimized for discovery, not verification. Claim-level evidence preserves Elly's `known`/`inferred`/`unknown` promise and prevents citations from giving unsupported conclusions a false appearance of certainty.

## 10. Operational Reliability Improvements

### 10.1 Transaction semantics

Elly must define behavior when response generation succeeds but persistence fails, persistence succeeds but auditing fails, evidence retrieval partially succeeds, or response composition fails after external work completes.

Results must distinguish successful execution, success with incomplete persistence, partial results, failure, and policy blocking. Critical audit or persistence failures must not be silently ignored.

### 10.2 Retry and idempotency

Retries must not unintentionally duplicate provider requests, stored turns, evidence records, audit events, or specialist executions. When a provider cannot guarantee idempotency, Elly should record that duplicate execution may have occurred.

### 10.3 Cancellation

On cancellation, Elly should stop initiating new external actions, cancel in-progress operations when supported, preserve already collected valid evidence when appropriate, record the task as cancelled, and never present partial output as a complete answer.

### 10.4 Configuration validation

Startup validation should detect missing required providers, unsupported model settings, invalid database configuration, incomplete privacy settings, incompatible capability combinations, and missing migrations. Errors should be early and actionable.

### 10.5 Failure taxonomy

| Status | Meaning |
|---|---|
| `FAILED` | Execution error prevented completion |
| `PARTIAL` | Valid results exist, but the workflow did not fully complete |
| `BLOCKED` | Policy or authorization prevented the operation |
| `UNKNOWN` | Evidence is insufficient to establish the answer |
| `UNAVAILABLE` | A required optional capability is not configured or operational |
| `CANCELLED` | The user or controlling system stopped the task |

These statuses must not be used interchangeably.

### 10.6 Sensitive logging

Logs and exceptions must not expose credentials, authentication tokens, full private prompts unless explicitly permitted, private retrieved content, consent-protected payloads, sensitive headers, or provider request bodies. Redaction must occur before data reaches the logging sink.

### 10.7 Context provenance

Elly should identify which approved context items influenced a response without exposing hidden reasoning. Provenance may include conversation-message IDs, user-profile fact IDs, evidence IDs, specialist-result IDs, and retrieval timestamps.

### 10.8 Migration compatibility

V1.5 schema changes must use explicit migrations, preserve readable V1 records, be tested against a representative V1 database, avoid rewriting historical migrations without a compelling reason, and document irreversible transformations.

## 11. Testing Strategy

### 11.1 Unit tests

Unit tests should cover routing, privacy classification, cloud authorization, evidence eligibility, capability availability, registry lookup and duplicate-ID rejection, failure mapping, response composition, and configuration validation without live models, databases, or networks unless the component is itself an integration boundary.

### 11.2 Contract tests

Each provider adapter should be tested against its application port for input validation, output normalization, error translation, timeouts, cancellation where supported, typed results, and containment of provider-specific details.

Every optional capability handler should also pass a shared contract suite covering its identifier, descriptor, availability behavior, supported-request check, typed execution result, and safe handling of unavailable dependencies.

### 11.3 Integration tests

Integration tests should cover orchestrator dispatch, persistence transactions, research retrieval and evidence construction, consent enforcement before cloud calls, unavailable capabilities, retries and duplicate prevention, and V1 data migration.

### 11.4 Required edge cases

- Search result found but page retrieval blocked.
- Misleading or unsupported search snippet.
- Source retrieved without a supporting passage.
- Conflicting sources or stale evidence.
- Missing privacy classification.
- Denied, expired, wrong-provider, or wrong-scope consent.
- Unavailable research or specialist capability.
- Duplicate capability identifiers during registration.
- A newly registered test capability dispatched without orchestrator changes.
- A model proposes an unregistered, unavailable, unauthorized, or schema-incompatible capability.
- Attempt to retrieve a required core service from the optional capability registry.
- Cancellation during research.
- Persistence failure after answer generation.
- Audit failure during completion.
- Duplicate retry attempt.
- Invalid startup configuration.
- Existing V1 database opened by V1.5.

### 11.5 Live verification

Mocked tests remain the default. Before release, a limited live suite should verify Ollama, the configured cloud provider, search, page retrieval, end-to-end evidence construction, and privacy blocking before transmission. Live tests must not use real private information.

## 12. Proposed V1.5 Requirements

These identifiers are provisional and should be reconciled with the authoritative SRS numbering scheme.

### 12.1 Architecture and maintainability

**V15-AR-001** — The conversation orchestrator shall coordinate workflows without directly implementing provider-specific, persistence-specific, privacy-classification, or evidence-eligibility mechanisms.

**V15-AR-002** — Routing, privacy authorization, and evidence-eligibility policies shall be testable without invoking a model, database, network service, or CLI.

**V15-AR-003** — Application workflows shall depend on provider-independent interfaces rather than concrete provider implementations.

**V15-AR-004** — Required application collaborators shall be validated during startup.

### 12.2 Capability contracts

**V15-CAP-001** — Elly shall represent optional capabilities through explicit typed availability states.

**V15-CAP-002** — Elly shall determine capability availability before selecting a workflow that requires that capability.

**V15-CAP-003** — Missing required dependencies shall produce a clear startup error.

**V15-CAP-004** — Core application behavior shall not use reflection or caught attribute errors to discover required collaborator methods.

**V15-CAP-005** — Dispatchable optional capabilities shall implement a common typed application contract and be registered through a capability registry during application composition.

**V15-CAP-006** — Adding a conforming optional capability shall not require modification of `ConversationOrchestrator`, `CapabilityRegistry`, or existing capability handlers.

**V15-CAP-007** — Required core policies and services shall remain explicit constructor dependencies and shall not be retrieved from the optional capability registry.

**V15-CAP-008** — Each registered capability shall expose a stable identifier, typed descriptor, explicit availability state, and typed execution result.

**V15-CAP-009** — Capability-specific provider boundaries shall use precise typed contracts rather than unstructured generic dictionaries.

### 12.3 Routing and boundaries

**V15-ROUTE-001** — A model-generated route shall be treated as a proposal; deterministic application policy shall authorize the final route.

**V15-ROUTE-002** — Final route decisions shall include a documented reason code suitable for diagnostics and auditing without recording hidden model reasoning.

**V15-ROUTE-003** — Elly may use registered capability descriptors to produce routing proposals, but deterministic policy shall validate registration, availability, input schema, privacy classification, consent, and authorization before execution.

**V15-BOUND-001** — Domain modules shall remain independent of concrete model, retrieval, storage, and user-interface implementations.

### 12.4 Privacy

**V15-PRIV-001** — Elly shall perform payload classification separately from cloud-transmission authorization.

**V15-PRIV-002** — Payload classification shall not itself grant transmission permission.

**V15-PRIV-003** — Elly shall deny cloud transmission when classification is absent, unclassified, or ambiguous.

**V15-PRIV-004** — Cloud authorization shall validate destination, payload scope, capability, consent scope, and consent validity before transmission.

**V15-PRIV-005** — Authorization decisions shall be auditable without unnecessarily storing the protected payload.

### 12.5 Evidence and epistemic status

**V15-EVID-001** — Every material externally sourced claim classified as `known` shall reference eligible claim-level evidence.

**V15-EVID-002** — Search-result snippets and metadata alone shall not establish a substantive claim as `known`.

**V15-EVID-003** — Eligible evidence shall identify the supporting content, source, retrieval time, validation status, and claim-support relationship.

**V15-EVID-004** — When supporting content cannot be retrieved or validated, Elly shall mark the affected claim unverified, `unknown`, or `blocked`.

**V15-EVID-005** — Elly shall downgrade unsupported claims before final response composition.

**V15-EVID-006** — Elly shall represent materially conflicting evidence rather than silently selecting a conclusion.

### 12.6 Reliability and operations

**V15-REL-001** — Elly shall distinguish `FAILED`, `PARTIAL`, `BLOCKED`, `UNKNOWN`, `UNAVAILABLE`, and `CANCELLED` outcomes.

**V15-REL-002** — Retried operations shall use idempotency controls where supported and shall record possible duplicate execution where it cannot be excluded.

**V15-REL-003** — Cancellation shall prevent new external actions and shall not present partial output as complete.

**V15-REL-004** — Startup shall validate required providers, supported model configuration, database configuration, privacy settings, capability compatibility, and migration state.

**V15-REL-005** — Critical persistence and audit failures shall be surfaced and shall not be silently ignored.

**V15-REL-006** — Sensitive information shall be redacted before reaching logs or exception sinks.

**V15-REL-007** — V1.5 migrations shall preserve readable V1 data and be verified against a representative V1 database.

### 12.7 Naming

**V15-NAME-001** — Active user-facing interfaces and current documentation shall identify the assistant as Elly.

**V15-NAME-002** — The rename shall preserve V1 data compatibility and shall not require rewriting historical migrations solely for naming consistency.

## 13. Recommended Implementation Order

1. Establish regression tests for current V1 behavior.
2. Rename user-facing Jarvis references to Elly in a dedicated change.
3. Introduce typed ports, request/result objects, startup composition validation, and the typed optional-capability registry.
4. Separate privacy classification from authorization and add fail-closed tests.
5. Implement claim-level evidence eligibility and epistemic-status enforcement.
6. Extract routing, context, workflow, persistence, audit, and composition responsibilities incrementally from `ConversationOrchestrator`; verify that a test capability can be registered and dispatched without changing it.
7. Standardize failure states, retry/idempotency behavior, cancellation, and sensitive logging.
8. Add and validate database migrations.
9. Run unit, contract, integration, migration, and limited live verification suites.

This order addresses correctness and safety before broader maintainability work while keeping each change reviewable and reversible.

## 14. Decision Summary

| Finding | V1.5 decision | Reason |
|---|---|---|
| Large orchestrator | Retain it as a thin coordinator and extract independent policies/mechanisms | One lifecycle coordinator is useful, but policy and infrastructure need independent tests and change boundaries |
| Optional collaborators and `getattr()` | Keep core dependencies explicit; use a typed registry for dispatchable optional capabilities | Prevents late failures while allowing new optional features without orchestrator changes |
| Capability registry scope | Store only dispatchable optional capabilities, never required core services | Avoids turning the registry into a service locator that hides dependencies |
| Optional-capability routing | Use descriptors for proposals and deterministic policy for execution approval | Reduces routing edits without allowing a model to authorize actions |
| Blurred boundaries | Place provider-independent state in domain, workflows/policies in application, mechanisms in infrastructure, and presentation in interfaces | Clarifies dependency direction without over-engineering the domain |
| Privacy coupling | Separate classification from authorization and fail closed | Classification must never be mistaken for permission |
| Metadata-only hosted research | Require retrievable claim-level evidence for `known` claims | Search metadata discovers sources but does not reliably verify claims |

## 15. Completion Criteria

Elly V1.5 is complete when:

- All approved V1.5 requirements are traceable to design elements and tests.
- Existing V1 behavior passes regression testing except for documented intentional changes.
- Existing V1 data can be opened and used after migration.
- The Elly rename is complete in active user-facing surfaces.
- Required dependencies fail clearly at startup when absent.
- Optional capability absence is explicit and handled before route execution.
- A conforming test capability can be added and dispatched without modifying the orchestrator, registry, or existing handlers.
- Required core services remain explicit and are not resolved through the optional capability registry.
- Capability proposals cannot bypass deterministic validation and authorization.
- Cloud transmission is blocked unless classification and authorization both succeed.
- No material external claim is labeled `known` without eligible claim-level evidence.
- Operational outcomes use the standardized failure taxonomy.
- Unit, contract, integration, migration, and limited live verification suites pass.

---

## 16. Status of Decisions

All decisions in this document remain **proposed** until reconciled with and approved for the authoritative Elly SRS and design specification. Class and interface names are recommendations; behavioral guarantees and acceptance criteria should become authoritative only after review.

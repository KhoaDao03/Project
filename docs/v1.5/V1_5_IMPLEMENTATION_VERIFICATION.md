# Elly V1.5 Implementation Verification and Improvement Proposal

**Verification date:** 2026-08-07  
**Reviewed baseline:** current working tree  
**Authority used for this review:** [REQUIREMNETS.md](REQUIREMNETS.md) and
[TECHNICAL_DESIGN.md](TECHNICAL_DESIGN.md)  
**Decision:** **The independently actionable correctness/security blockers are
resolved, and the owner closed V1.5 on 2026-08-07.** Live-provider verification
was explicitly accepted as deferred evidence; it was not recorded as passing.
See [V1_5_CLOSURE.md](V1_5_CLOSURE.md).

> Note: the requirements filename is misspelled in the repository. This report
> keeps the existing link intact and recommends renaming it to `REQUIREMENTS.md`.

## 1. Executive summary

The working tree contains real V1.5 implementation work, not only scaffolding:

- deterministic routing and public reason codes;
- a typed optional-capability registry and research/specialist handlers;
- separate privacy classification and cloud authorization;
- local conversation and context collaborators;
- document retrieval and claim-evidence policy;
- explicit outcome codes, provenance, operation/idempotency records, and schema
  migration 3;
- focused routing, capability, authorization, evidence, retrieval, idempotency,
  composition, and migration tests.

The post-remediation regression baseline is healthy: **260 tests passed, 0 failed,
0 skipped**, Python compilation passed, and `git diff --check` passed. Targeted
failure-path regressions now cover the originally observed blockers:

1. redirect-to-private and DNS-rebinding exposure at the retrieval boundary;
2. untyped initial-audit failure before provider dispatch;
3. capability availability disagreeing with provider health;
4. specialist certainty and outcome-taxonomy bypasses;
5. cancellation stopping only the local model;
6. current claims lacking source-time policy and numeric conflict comparison;
7. consent not being explicitly capability-bound.

These issues were resolved with pinned redirect-safe retrieval, typed audit
failure behavior, health-aware availability, evidence-conservative specialists,
correct three-axis taxonomy, request-scoped cancellation, explicit freshness and
numeric conflict handling, and capability-bound/audited authorization.

The owner subsequently approved and closed the implemented V1.5 scope with the
live-provider exception documented in the closure record.

## 2. Verification performed

### 2.1 Documents and implementation inspected

- All 37 provisional `V15-*` requirements and their acceptance criteria.
- The complete V1.5 technical design and proposed integration sequence.
- Application orchestration, routing, capability contracts/handlers,
  authorization, privacy, research, evidence, response composition, and local
  conversation paths.
- OpenAI/Ollama/retrieval, SQLite, audit, and CLI boundaries.
- V1.5-focused and existing regression tests.
- Schema migrations, operation leases, provenance storage, and representative
  migration tests.

### 2.2 Commands and results

```text
PYTHONPATH=src python3 -W error::ResourceWarning -m unittest discover -s tests -t .
Ran 260 tests in 2.960s — OK

PYTHONPATH=src python3 -m compileall -q src tests
Pass

git diff --check
Pass
```

`ruff check src tests` passed. Strict `mypy` passed all 69 source files. Both are
mandatory in the checked-in GitHub Actions workflow alongside the unit suite,
compilation, and whitespace checks.

No paid provider call or full live V1.5 suite was run. The completion criterion
requiring limited live Ollama, cloud, search, retrieval, and privacy verification
therefore remains open.

### 2.3 Targeted diagnostics

Additional read-only diagnostics established that:

- an OpenAI research provider with no key reports health `disabled`, while its
  registered research capability reports `available`;
- specialist epistemic results `blocked` and `unknown` compose to task status
  `completed` with outcome code `success` when they contain explanatory text;
- forcing `task.received` audit failure raises `UnboundLocalError: cannot access
  local variable 'text'` instead of returning a typed `FAILED` result.

## 3. Findings

### V15-F01 — Resolved: redirect-safe, DNS-pinned document retrieval

**Affected requirements/design:** V15-EVID-003/004, claim-level retrieval safety,
fail-closed behavior.

[`http_document_retriever.py`](../../src/elly/adapters/http_document_retriever.py)
validates DNS for the initial hostname at lines 28–45, then calls the default
`urllib` opener at lines 47–50. That opener follows HTTP redirects, but the final
URL and every redirect hop are not revalidated. The adapter also records the
original canonical URL rather than the final response URL.

Consequences:

- a public URL can redirect to localhost, a private address, or a link-local
  metadata endpoint after passing the first check;
- DNS is resolved once for validation and again by the HTTP client, leaving a
  DNS-rebinding/TOCTOU window;
- evidence provenance can identify a different source from the content actually
  fetched;
- response content type and final scheme are not checked.

**Resolution:** retrieval now uses an explicit bounded redirect loop, validates
every target, pins the validated numeric socket while preserving TLS hostname
verification, rejects unsafe schemes/ports/addresses/content types, bounds bytes,
and records the final URL. Regression coverage includes private resolution and a
public-to-loopback redirect.

### V15-F02 — Resolved: initial audit failure is typed and pre-dispatch

**Affected requirements:** V15-REL-001, V15-REL-005, V15-REL-006.

In [`conversation.py`](../../src/elly/application/conversation.py), the
`task.received` audit exception handler references `bool(text)` at line 633, but
`text` is not assigned until the later local-execution block. A failing audit
therefore raises `UnboundLocalError`, bypassing `TaskResult`, operation cleanup,
and the CLI's typed-error handling.

**Resolution:** the invalid pre-assignment reference was removed. An initial audit
failure now returns `FAILED`, marks the operation without possible-duplicate
semantics, and dispatches no provider. Authorization audit also occurs before an
external call and fails closed.

### V15-F03 — Resolved: availability includes typed provider health

**Affected requirements:** V15-CAP-001/002/008, V15-REL-004.

`ResearchCapabilityHandler.status()` returns available whenever a pipeline object
exists; specialist status checks only manifest/workflow presence. Neither checks
the provider's typed health result. In normal composition, a research pipeline is
always constructed—even when `OPENAI_API_KEY` is absent—so routing selects an
apparently available capability that later fails at execution.

**Resolution:** research and specialist handlers now report unavailable when the
underlying provider is disabled or unavailable, before authorization/dispatch.

### V15-F04 — Resolved: specialist certainty cannot bypass evidence policy

**Affected requirements:** V15-EVID-001/002/003/005.

The research pipeline creates `ClaimSupport` records, but specialist composition
accepts a provider's epistemic string directly. `SpecialistCapabilityHandler`
passes the provider status and arbitrary source strings to `compose_specialist`
without evidence eligibility. A hosted specialist can therefore return `known`
with no claim-to-passage relationship, content hash, retrieval validation, or
freshness evidence.

This violates the system-wide wording “every material externally sourced claim,”
even though the dedicated research path is more conservative.

**Proposed resolution:** all externally sourced `known` results must pass through
one evidence gate. Either prohibit specialists from returning `known` unless they
consume already validated `ClaimSupport` records, or downgrade unsupported
specialist claims to `inferred`/`unknown`. Do not render specialist-provided URLs
as validated citations until they pass citation and evidence policy.

### V15-F05 — Resolved: specialist taxonomy preserves unknown and blocked

**Affected requirements:** V15-REL-001 and V15-EVID-004/005.

[`compose_specialist`](../../src/elly/application/response_composer.py) sets every
non-partial specialist result to task status `COMPLETED` and outcome code
`SUCCESS`, regardless of whether its epistemic status is `UNKNOWN` or `BLOCKED`.
It also stores assumptions in the `claims` field.

**Proposed resolution:** introduce a single, exhaustively tested mapping from
specialist status to task status, epistemic status, validation status, and outcome
code. At minimum, `unknown` must use outcome `UNKNOWN`; `blocked` must use task and
outcome `BLOCKED`; provider execution failures must use `FAILED`; and assumptions
must remain separate from claims.

### V15-F06 — Resolved: request-scoped cancellation covers provider boundaries

**Affected requirements:** V15-REL-003 and required cancellation edge cases.

A thread-safe request-scoped cancellation token now reaches local generation,
hosted research, retry checks, document retrieval, and specialists. Provider
close/cancel callbacks unblock active I/O, and provider errors caused by closure
are normalized to `CancelledError`. Dedicated regressions cover cancellation
during hosted research, between retries, during retrieval, and during specialist
execution.

### V15-F07 — Substantially resolved: freshness and numeric conflicts are evidence-level

**Affected requirements:** V15-EVID-003/006 and time-sensitive acceptance criteria.

`EvidencePolicy.evaluate()` accepts `now` but never uses it. Its eligibility test
is a case-insensitive substring search over raw retrieved content. The research
pipeline detects conflict only when provider prose contains words such as
“conflict,” “disagree,” or “prices vary.” It does not compare normalized claim
records or source publication/quote timestamps.

Consequences:

- a newly retrieved old page can support a supposedly current fact;
- two incompatible eligible passages can both be treated as supported unless the
  provider explicitly narrates the conflict;
- text in scripts, metadata, navigation, or negated context can satisfy the raw
  substring check.

**Proposed resolution:** parse bounded visible document content, retain source
publication/quote time separately from retrieval time, apply claim-type freshness
rules, and compare normalized structured claims for conflicts. A current claim
without source-time evidence should remain unverified. Add stale-current,
implicit-conflict, negation, script-only, and publication-time tests.

Official OpenAI documentation describes web-search URL annotations as containing
the URL/title and the location in the model response where the source was used;
it does not state that those offsets are independently retrieved page passages.
Treating the annotation span as a candidate claim passage is therefore an Elly
inference that must still be validated by retrieval and evidence policy.
[Official OpenAI web-search documentation](https://developers.openai.com/api/docs/guides/tools-web-search)

### V15-F08 — Resolved: consent and authorization audit are capability-bound

**Affected requirements:** V15-PRIV-004/005.

`CloudAuthorizationPolicy` receives `capability_id`, but `ConsentProposal` and
`ConsentWorkflow.check()` do not store or compare it. Purpose usually differs per
capability, but a purpose string is not an explicit capability binding. The
`requires_consent` descriptor flag is also not consulted by authorization.
Authorization audit records do not consistently retain the classification,
payload digest, capability, destination, and decision reason required to
reconstruct why an allowed transmission was authorized.

**Proposed resolution:** bind proposals and one-use approvals to capability ID,
destination, model, exact payload digest, declared scope/categories, purpose,
cost, and expiry. Emit a redacted authorization-decision event before every
external dispatch. Test wrong-capability reuse even when all other fields match.

### V15-F09 — Medium-high: the orchestrator is still the dominant policy/finalization component

**Affected requirements:** V15-AR-001/004, V15-CAP-003/007.

Policies and handlers were extracted, which is meaningful progress, but
`ConversationOrchestrator` remains approximately 796 lines and still owns:

- default construction of routing, context, privacy, authorization, capability,
  and local-conversation collaborators;
- task/operation persistence ordering and duplicate recovery;
- audit sequencing and failure mapping;
- authorization/consent orchestration;
- capability dispatch, result persistence, source/provenance writes, and final
  response composition.

Several collaborators described as required by the design are optional constructor
arguments with silent defaults. Startup validation checks clock, generalist,
repository, and audit, but not the routing, context, privacy, authorization,
response-composition, or local-use-case contracts.

**Proposed resolution:** inject required policies/use cases explicitly from the
composition root and reject missing/incompatible implementations. Extract a
typed task-finalization/unit-of-work collaborator that owns persistence/audit
ordering and partial-failure semantics. Keep the orchestrator as a short lifecycle
coordinator. Do this incrementally behind characterization tests.

### V15-F10 — Medium: retry/idempotency evidence is incomplete

**Affected requirement:** V15-REL-002.

The SQLite operation lease prevents repeated top-level dispatch and correctly
marks uncertain external failures. However, research retries happen inside one
operation, do not pass a provider idempotency key, and do not persist attempt
number or disclose possible duplicate provider execution after a transient first
attempt succeeds on retry.

**Proposed resolution:** persist each provider attempt under the operation ID,
reuse provider idempotency keys where supported, and retain a safe
`possible_duplicate_execution` flag when a timed-out/transient attempt may have
run. Read-only search retries may use a lower-severity user presentation, but the
audit record should remain accurate.

### V15-F11 — Resolved: representative V2-to-V3 migration verification

**Affected requirement:** V15-REL-007.

A checked-in sanitized schema-version-2 SQL fixture now includes representative
session, message, task, profile, tombstone, audit, and source records. Tests
migrate that fixture, verify all record classes, execute a complete new task on
the same database, verify rollback/version stability on a failed V3 statement,
and reject unknown future schema versions at startup.

### V15-F12 — Resolved: static gates and owner document approval

**Affected requirements:** V15-CAP-004/008/009 and completion governance.

Strict `mypy` now passes all source files, Ruff passes the stable error/import
ruleset, capability consent is domain-typed, and the checked-in CI workflow makes
static analysis, tests, compilation, and whitespace validation mandatory.

The owner approved the implemented requirements and closed V1.5 on 2026-08-07.
The historical filename `REQUIREMNETS.md` remains misspelled but is retained to
avoid breaking existing references; a later documentation-only rename may update
all links atomically.

## 4. Requirement verification matrix

`Pass` means deterministic implementation evidence exists for the reviewed
working tree. It does not imply live-provider or release acceptance. `Partial`
means the central mechanism exists but one or more acceptance clauses remain
unmet. `Fail` means observed production behavior contradicts the requirement.

**Summary after remediation:** 29 pass, 8 partial, 0 fail.

| Requirement | Status | Verification summary |
|---|---|---|
| V15-AR-001 | Partial | Policies extracted, but the 796-line orchestrator still owns persistence/audit/finalization and builds default collaborators |
| V15-AR-002 | Pass | Routing, privacy/authorization, and evidence policy have network-free unit tests |
| V15-AR-003 | Pass | Application workflows generally use typed provider ports |
| V15-AR-004 | Partial | Four core ports validated; several design-required policies/use cases silently default |
| V15-CAP-001 | Pass | Typed descriptor/status/availability contracts exist |
| V15-CAP-002 | Pass | Handler availability now incorporates typed provider health |
| V15-CAP-003 | Partial | Core provider ports fail early; required V1.5 policies/use cases are not all validated |
| V15-CAP-004 | Pass | No reflective collaborator discovery remains in application code |
| V15-CAP-005 | Pass | Optional handlers implement and register through `CapabilityRegistry` |
| V15-CAP-006 | Pass | Test capability dispatches without orchestrator/registry edits |
| V15-CAP-007 | Pass | Registry is limited to optional executable handlers |
| V15-CAP-008 | Pass | Capability contracts, availability, and consent proposal are domain-typed |
| V15-CAP-009 | Pass | Capability-specific provider ports use typed DTOs rather than generic dictionaries |
| V15-ROUTE-001 | Pass | Route proposal is untrusted and deterministic policy returns the decision |
| V15-ROUTE-002 | Pass | Typed public reason codes are implemented and audited |
| V15-ROUTE-003 | Partial | Registration/schema/provider availability and later authorization are checked; full proposal-policy coverage remains incomplete |
| V15-BOUND-001 | Pass | No concrete infrastructure/interface imports were found in domain modules |
| V15-PRIV-001 | Pass | `PrivacyPolicy` and `CloudAuthorizationPolicy` are separate |
| V15-PRIV-002 | Pass | Cloud mode and authorization are checked after classification |
| V15-PRIV-003 | Pass | Unclassified external payloads fail closed |
| V15-PRIV-004 | Partial | Exact payload/provider/model/capability/scope/cost/expiry checks exist; descriptor consent semantics remain incomplete |
| V15-PRIV-005 | Pass | Redacted authorization decision metadata is persisted before external dispatch |
| V15-EVID-001 | Pass | Unsupported specialist `known` assertions are downgraded and unvalidated URLs are not verified citations |
| V15-EVID-002 | Pass | Metadata/snippets/source strings cannot become known without eligible claim support |
| V15-EVID-003 | Partial | Claim links/hash/retrieval and source-time freshness exist; richer claim-type freshness remains future work |
| V15-EVID-004 | Pass | Retrieval and specialist eligibility failures downgrade without fabricated success |
| V15-EVID-005 | Pass | Unsupported external claims are consistently inferred, unknown, or blocked |
| V15-EVID-006 | Partial | Numeric current-market conflicts are structural; general semantic conflicts remain heuristic |
| V15-REL-001 | Pass | Specialist unknown/blocked/partial mappings preserve distinct task and outcome codes |
| V15-REL-002 | Partial | Top-level operation lease exists; individual retry attempts/idempotency are incomplete |
| V15-REL-003 | Pass | One request-scoped token interrupts local, research, retrieval, and specialist provider boundaries |
| V15-REL-004 | Pass | Config/provider health checks and future-schema rejection fail early |
| V15-REL-005 | Pass | Pre- and post-dispatch audit/persistence failures return typed failed or partial outcomes |
| V15-REL-006 | Pass | Redacted audit contracts and tests exist; no raw-body audit fields observed |
| V15-REL-007 | Pass | Representative V2 data migrates transactionally and runs a complete V1.5 task |
| V15-NAME-001 | Pass | No active non-historical `Jarvis` references were found |
| V15-NAME-002 | Pass | Migrations are additive and historical data is not rewritten for naming |

## 5. Prioritized remediation plan

### Completed P0/P1 blocker remediation

1. Hardened document redirects, DNS binding, final URL, content type, and provenance.
2. Fixed and tested pre-dispatch audit failure.
3. Made capability availability reflect provider health.
4. Applied evidence-before-certainty to specialists and corrected taxonomy.
5. Propagated cancellation across external boundaries.
6. Added source-time freshness, numeric conflict detection, and capability-bound consent/audit.

### Carried to the next iteration as improvements

7. Extract typed finalization/unit-of-work behavior and make required V1.5
   collaborators explicit (`V15-F09`).
8. Persist provider-attempt/idempotency metadata (`V15-F10`).

### Closure decisions

9. Owner approval was recorded on 2026-08-07 (`V15-F12`).
10. Limited live-provider verification was accepted as deferred evidence; it was
    not recorded as passing.

## 6. Regression coverage and remaining tests

Implemented blocker regressions:

- Initial audit sink failure returns `FAILED`, performs no provider call, and
  leaves a consistent operation/task record.
- Public URL redirecting to private/link-local/localhost is rejected at every hop.
- Provider disabled/missing key means capability unavailable before route dispatch.
- Specialist `known` without `ClaimSupport` is downgraded; unvalidated specialist
  URLs are not rendered as verified citations.
- Specialist `unknown`, `blocked`, `partial`, and provider failure map to distinct
  task/outcome codes.
- Active request cancellation interrupts the bound provider and returns
  `CANCELLED` rather than success.
- Two eligible sources with incompatible structured values produce a conflicted
  claim without relying on provider wording.
- Current claim with only retrieval time—but no source/quote time—cannot be known.
- Consent for capability A cannot authorize capability B when every other field is
  identical.

Migration, external cancellation, strict typing, lint, compilation, and
whitespace verification are now covered by the local suite and CI workflow.

## 7. Final assessment

V1.5 has a sound direction and meaningful implementation progress. The separation
of routing, authorization, optional capability dispatch, evidence policy, outcome
codes, operation leases, and provenance is materially better than V1. The current
suite demonstrates that the happy paths and many deterministic policies work.

The independently actionable verification blockers are closed. The owner accepted
the implemented scope and closed V1.5 on 2026-08-07. Live-provider verification
remains explicitly deferred and must be run before any later production decision
that relies on current provider behavior. Architecture reduction and attempt-level
retry durability are carried forward as non-blocking improvements.

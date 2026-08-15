# Elly V2 Phase 0 Contract and Characterization Freeze

**Status:** Superseded; V2 completed and closed by owner decision on 2026-08-15

**Baseline:** V1.5 implementation at the start of V2 work

**Original scope:** Contract reconciliation and characterization only. The
approval record in section 5 now authorizes Phases 1–6 within the reconciled
boundaries below.

## 1. Authority and interpretation

The documents and code are interpreted in this order:

1. `docs/v1/REQUIREMENT.md` is the authoritative Version 1 SRS for V1 scope,
   non-goals, requirement IDs, and acceptance behavior.
2. `docs/v1/DECISIONS.md` records the owner's approved V1 decisions and approved
   deviations from earlier design material.
3. The V1.5 closure and verification records describe the accepted V1.5
   implementation scope. Source code and executable tests are the evidence for
   behavior that is already implemented.
4. `docs/v2/REQUIREMENTS.md` is the approved V2 requirement set and
   `docs/v2/TECHNICAL_DESIGN.md` is its implemented design guide.

The original direct implementation request authorized Phase 0 only. On
2026-08-15, the owner subsequently requested that all V2 blocking findings be
addressed, authorizing Phases 1–6 within this frozen scope.

## 2. Reconciliation with the authoritative V1 SRS

| V2 requirement | Reconciliation | Phase 0 boundary or constraint |
| --- | --- | --- |
| V2-ARCH-001 | Compatible with AI-002, AI-001, and NFR-006. It is an internal dependency-wiring correction. | Preserve the required local generalist and public CLI behavior while removing the unsupported mutation seam in a later phase. |
| V2-ARCH-002 | Compatible with AI-002, FR-006, and the V1 failure taxonomy. | Extract the optional workflow later without changing local conversation into an optional capability. |
| V2-CAP-001 | Compatible with BUS-003, AI-003, AI-005, and AI-015. Registry dispatch is an extensibility mechanism, not a service locator. | Research and coding remain the V1 optional specialist capabilities. No external communication, purchasing, trading, arbitrary execution, or destructive capability may be enabled. |
| V2-INTENT-001 | Compatible with AI-002, AI-005, AI-011, and AI-012. Model intent remains untrusted and application validation remains authoritative. | Keep existing deterministic signals as characterization evidence; do not replace routing in Phase 0. |
| V2-AUTH-001 | Compatible with AI-014 and SEC-001/002/005. The approved three-tier privacy mapping and exact consent rules in DEC-M5-01 remain authoritative. | Preserve the approved hosted `web_search` scoped exception in DEC-OQ-07; no provider may become an authorization authority. |
| V2-AUTH-002 | The typed risk policy is compatible with SEC-005, but effectful V1 actions are explicitly out of scope under SRS §§3.6 and 6.4. | Defer execution of external communications, account changes, financial actions, purchases, trades, and destructive operations. A later phase may define policy contracts, but it must not activate those effects without an approved scope amendment. |
| V2-SESSION-001 | Compatible with AI-014, DATA-001/005, OPS-004, DEC-OQ-06, and DEC-OQ-08. Durable cloud mode strengthens the existing session authority. | The current CLI mode behavior is characterized as a known gap; durable compare-and-set mutation belongs to Phase 1. |
| V2-API-001 | Compatible with DEC-OQ-02: CLI first, interface-independent core, local web only after the core is reliable. | Phase 1 may add an in-process façade and contract-test adapters. A production web server, authentication, multi-user tenancy, and deployment are not included. |
| V2-CLI-001 | Compatible with FR-001 and UX-001. Existing command names and user-visible behavior remain compatibility targets. | Modular dispatch is a later refactor; Phase 0 only characterizes the current command surface. |

Cross-cutting V1 constraints remain frozen: single-user local operation,
localhost-only provider boundaries, local Ollama for the required generalist,
one configurable hosted provider, bounded delegation depth, application-owned
policy, redacted audit data, and no silent cloud fallback.

## 3. Current behavior characterized

The Phase 0 characterization suite is
`tests/test_v2_phase0_characterization.py`. It records these observable V1.5
behaviors before later refactoring:

- `/help`, `/new --no-store`, `/mode`, plain-text submission, and `/cancel` are
  handled by `Cli.dispatch()` and produce the existing terminal responses.
- Timeless requests route to `local_generalist`; current-information requests
  route to `web_research`; coding and research-specialist signals retain their
  existing route decisions.
- Successful local work is `COMPLETED` with `SUCCESS`, `INFERRED`, and
  `VALIDATED` axes; provider failure is `BLOCKED` and does not produce a
  fabricated answer.
- The current local persistence order is: read prior context, start/claim the
  task operation, record receipt, persist the user turn, invoke the provider,
  persist the assistant turn, record completion, finish the task, and complete
  the operation.
- Owner-specific cloud payloads require exact, one-time consent bound to the
  payload and provider metadata; the provider is not called before approval.
- Cancellation by the current active-operation API produces `CANCELLED`, does
  not produce success, and interrupts a bound provider when supported.

Existing V1/V1.5 tests continue to cover the detailed research, persistence,
specialist, guardrail, redaction, migration, and provider-adapter matrices. The
new module is intentionally a small cross-cutting characterization layer rather
than a duplicate replacement for those suites.

## 4. Frozen V2 public-contract decisions

These are design decisions for implementation and review; they do not add a V2
runtime API during Phase 0.

### Public boundary

- The public in-process boundary is named `EllyApplication` and is documented as
  `api/v2`.
- Public requests and views are immutable DTOs. They do not expose repositories,
  SQLite rows, ports, provider SDK objects, exceptions, mutable services, or
  secrets.
- `SubmitRequest` carries request ID, session ID, validated text, and optional
  intent/approval correlation. It does not carry authoritative cloud or
  persistence mode; the application loads those values from the session store.
- Task reads and cancellation are task-ID based. V2 uses `cancel_task(task_id)`;
  `cancel_active()` remains a V1 characterization only.

### Results and errors

- `ApiResult[T]` is either a value or an `ApiFailure` with a safe message,
  retryability, and correlation ID.
- Public failure codes are `INVALID_INPUT`, `NOT_FOUND`, `CONFLICT`, `BLOCKED`,
  `UNAVAILABLE`, `CANCELLED`, and `INTERNAL_FAILURE`.
- Existing task, epistemic, and validation axes retain their meanings.
  `UNAVAILABLE`, `UNKNOWN`, `PARTIAL`, `FAILED`, and `CANCELLED` are not
  repurposed.
- V2 adds distinct meanings for clarification and consequential-action
  confirmation: `CLARIFICATION_REQUIRED` and `AWAITING_CONFIRMATION`. They are
  later-phase contract additions, not Phase 0 code changes.

### Session, approval, and redaction

- A session's cloud mode is authoritative and durable. Mode updates use an
  expected version and return a typed conflict instead of silently overwriting a
  newer update.
- Cloud consent and action confirmation are different approvals, with different
  digests, scopes, expiry, and user-facing meanings.
- Trace, source, profile, status, and consent views are redacted at the
  application boundary. Audit records retain allowlisted metadata only.

### Compatibility

- Additive public fields with defaults are compatible. Removing a field, changing
  enum meaning, or changing required behavior requires an explicit compatibility
  decision and a new major API version.
- Existing V1.5 CLI workflows remain user-compatible unless a V2 requirement
  explicitly corrects a behavior. Durable `/mode` persistence is such an
  explicit correction and must be introduced with migration and parity tests.
- V2 must preserve the V1 non-goals and must not turn a model proposal into
  authorization for external or consequential action.

## 5. Approval and deferral record

On 2026-08-15 the owner directly requested resolution of all findings from the
V2 implementation audit. This records approval to implement:

1. all nine V2 requirement IDs;
2. the frozen V2 public DTO/error/status decisions;
3. typed consequential-action authorization while retaining the deferral of
   actual external communication, financial, account, deletion, and other
   effectful capabilities; and
4. minimal in-process CLI, web, desktop/mobile, and REST parity adapters, while
   production web/authentication remains out of scope.

The owner marked V2 completed on 2026-08-15 after deterministic verification.
Limited live-provider quality verification is retained as an accepted deferred
exception and is not claimed as passed. Evidence and closure are recorded in
`V2_IMPLEMENTATION_VERIFICATION.md` and `V2_CLOSURE.md`.

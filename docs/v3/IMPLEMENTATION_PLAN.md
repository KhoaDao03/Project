# Elly V3 Implementation and Verification Plan

**Status:** Completed and closed 2026-08-16
**Baseline:** V2.5 completed and closed 2026-08-15
**Requirements:** [REQUIREMENTS.md](REQUIREMENTS.md)
**Design:** [TECHNICAL_DESIGN.md](TECHNICAL_DESIGN.md)

Phase 0 through Phase 9 are implemented and verified. The owner requested
end-to-end verification and closure on 2026-08-16. Hosted-capability live
verification is the explicitly recorded environment-dependent exception; local
Ollama planner and synthesis verification passed.

## 1. Delivery principles

- Preserve a runnable, tested application at every phase.
- Introduce typed contracts before orchestration behavior.
- Keep model output advisory and validate it before persistence or execution.
- Reuse the V2.5 registry and authorization boundaries.
- Add persistence through forward-only, idempotent migrations.
- Migrate one capability end to end before enabling parallel execution.
- Keep planner, execution, status aggregation, and finalization as separate
 application services.
- Do not claim live-provider quality from fixtures or fake adapters.

## 2. Phase 0 — Contract freeze and characterization

### Work

- Approve or explicitly defer each V3 requirement.
- Freeze current V2.5 behavior for local conversation, single-capability
 routing, consent, cancellation, result persistence, task views, and traces.
- Record representative schema-v6 fixtures.
- Define the initial proposal, plan, result, and synthesis schema identifiers.
- Freeze enum vocabularies for plan/step states, criticality, finalization,
 proposal disposition, and safe rejection codes.
- Approve the named-profile and independent-role-binding migration and
 deprecation window.
- Freeze initial restart recovery at conservative interruption marking and
 policy-controlled resume; never automatically reissue uncertain external work.

### Tests

- V2.5 characterization remains green.
- Schema-v6 fixture loads and executes a new V2.5 task.
- Static boundaries record current orchestration and configuration ownership.

### Exit gate

No unresolved decision changes public status semantics, stored data shape,
authorization scope, or configuration precedence.

## 3. Phase 1 — Independent local-model roles

### Work

- Add a validated named profile catalog, immutable `LocalModelRoleConfig`, and
 role-limit configuration contracts.
- Add `[local_models.profiles.*]`, `[local_models.roles]`,
 `[local_models.role_limits]`, and `ELLY_LOCAL_MODELS_*` parsing.
- Bind conversation, planning, and synthesis independently; initially point all
 three bindings to the existing local Ollama profile.
- Migrate conversation composition to the resolved `conversation` role.
- Implement the documented old-key migration precedence and one bounded
 deprecation warning.
- Add non-secret profile data to health/status views.
- Keep remote research and specialist configuration independent.
- Migrate the V3 acceptance-profile defaults to three provider calls and two
 concurrency slots while preserving operator-configured lower ceilings.

### Likely files

- `src/elly/config.py`
- `config.example.toml`
- `src/elly/composition.py`
- `src/elly/api/contracts.py`
- `src/elly/api/application.py`
- `src/elly/presentation/render.py`
- `tests/test_config.py`
- status/interface parity tests

### Tests

- defaults, TOML, explicit file, and environment precedence;
- default bindings reuse one profile without coupling the role contracts;
- rebinding planner changes only planner, with equivalent tests for conversation
 and synthesis;
- updating a shared profile changes only the roles intentionally bound to it;
- role limits do not duplicate profile identity;
- conflicts, invalid endpoints, missing identity, and unsupported providers fail;
- status output is equivalent and redacted across interfaces; and
- remote selections do not change with local profiles or role bindings.

### Exit gate

Conversation still works through the existing local model. Planner and
synthesizer receive independent immutable role configurations and can be
rebound without affecting conversation or each other.

## 4. Phase 2 — Versioned orchestration contracts and local planner

### Work

- Add proposal, proposed-step, plan-step, input-binding, limit-snapshot, and
 finalization contracts.
- Add strict schema codecs with unknown-field and size rejection.
- Define `LocalPlannerPort` and fake/recorded adapters.
- Implement the local Ollama structured planner adapter using the resolved
 `planner` role.
- Build a minimized model-safe routing catalog view.
- Validate capability-first proposals against a fresh V2.5 registry snapshot.
- Implement clarification and deterministic single-route fallback.

### Likely modules

- `src/elly/planning/contracts.py`
- `src/elly/planning/codec.py`
- `src/elly/application/plan_interpreter.py`
- `src/elly/ports/local_planner.py`
- `src/elly/adapters/ollama_planner.py`
- `src/elly/adapters/fake_planner.py`

### Tests

- local-only, single-capability, research-plus-specialist, and two-specialist
 proposal fixtures;
- malformed JSON/schema, excessive output, unknown fields, and unsafe IDs;
- provider named as capability;
- stale/unknown/unavailable capability and unsupported operation;
- ambiguity/clarification; and
- planner timeout or malformed output uses only the permitted deterministic
 fallback and never creates an unvalidated multi-step plan.

### Exit gate

V3-ROUTE-001, V3-ROUTE-002, and the proposal portion of V3-CONFIG-001 pass
without executing a capability.

## 5. Phase 3 — Pure DAG validation and persistence

### Work

- Implement pure proposal-to-plan construction.
- Add graph indexing, deterministic topological sort, and cycle detection.
- Validate dependencies, type flow, availability, freshness, effects,
 finalization, objective metadata, and all plan limits.
- Add deterministic redundancy fingerprints and narrow verification markers.
- Add schema migration 7 and plan repository methods.
- Persist a validated plan atomically before any step begins.

### Likely modules

- `src/elly/application/plan_builder.py`
- `src/elly/application/plan_validation.py`
- `src/elly/application/redundancy_policy.py`
- `src/elly/ports/plan_repository.py`
- `src/elly/adapters/sqlite_repository.py`

### Tests

- linear, diamond, and parallel DAGs;
- direct/indirect cycles and self-dependency;
- duplicate/missing IDs and incompatible input/output types;
- unsupported capability operations and unavailable capabilities;
- zero/one terminal synthesis rules;
- every configured limit boundary;
- exact redundancy, distinct perspectives, and authorized verification;
- registry-order independence; and
- schema-v6 to schema-v7 migration, rollback on failure, and idempotent rerun.

### Exit gate

V3-PLAN-001 and V3-PLAN-003 pass using pure services and an in-memory
repository, with no model or provider needed.

## 6. Phase 4 — Bounded dependency scheduler

### Work

- Implement `PlanOrchestrator` and `PlanExecutor` separately from conversation.
- Add persisted step transitions and dependency-ready scheduling.
- Enforce global, specialist, research, synthesis, parallelism, timeout, and
 provider-call ceilings.
- Reuse request-scoped cancellation and capability-registry dispatch.
- Propagate mandatory dependency failure and allow eligible optional branches.
- Add operation leases before provider dispatch.
- Start with one migrated existing capability and sequential execution; enable
 parallel ready steps only after transition invariants pass.

### Tests

- one-step execution equivalence with V2.5;
- sequential dependencies;
- two independent bounded steps in parallel;
- third specialist rejected at the configured maximum;
- mandatory failure skips descendants;
- optional failure leaves independent work eligible;
- cancellation before dispatch, while queued, and during parallel execution;
- timeout and circuit failure; and
- no handler can add an undeclared step or invoke another handler directly.

### Exit gate

V3-PLAN-002 scheduling, termination, and cancellation criteria pass with fake
capabilities under repeated concurrency stress.

## 7. Phase 5 — Per-step authorization and typed results

### Work

- Resolve and minimize actual step inputs immediately before authorization.
- Reclassify derived results before cross-capability/provider transmission.
- Bind consent and cost reservation to plan/step, provider, purpose, payload
 hash, expiry, capability, and operation.
- Preserve semantic action authorization and exact confirmation.
- Introduce versioned `StepResultEnvelope` normalization.
- Extend capability contract tests to required input/output schema versions.
- Reject malformed results and unverifiable action completion receipts.

### Tests

- structural approval cannot bypass execution-time authorization;
- consent mismatch by provider, purpose, payload, expiry, or step;
- denied step makes no provider call;
- derived private output cannot cross an unauthorized boundary;
- cloud denial retains eligible local work;
- malformed/old/unknown result schema;
- evidence absence versus contradiction;
- provider exceptions are normalized; and
- action success without a verified receipt is rejected.

### Exit gate

V3-EXEC-001 and V3-EXEC-002 pass across CLI, application API, and all interface
test adapters.

## 8. Phase 6 — Aggregation and deterministic finalization

**Status:** Implemented and verified

### Work

- Implement pure step-to-plan status derivation and precedence table.
- Add disagreement records based on typed claims/findings.
- Implement `DIRECT` and `TEMPLATE` finalizers first.
- Preserve completed eligible work for partial results.
- Expose plan and step status through additive task/result views.

### Tests

- every row in the status decision table;
- simultaneous cancellation/terminal-transition ordering;
- required and optional failures;
- unavailable, blocked, skipped, and cancelled branches;
- disagreement is explicit and cannot become consensus; and
- exact receipts/status/audit records use deterministic templates.

### Exit gate

V3-RES-001 and the deterministic portions of V3-SYN-002 pass without a local
model.

## 9. Phase 7 — Evidence-bounded local synthesis

**Status:** Implemented and verified

### Work

- Define `LocalSynthesisPort`, strict synthesis input/draft schemas, and fake
 adapters.
- Implement the Ollama synthesis adapter using the resolved `synthesis` role.
- Build minimized approved synthesis input.
- Implement claim-reference, citation, warning, disagreement, and status
 validators.
- Render canonical validated claim text deterministically from the accepted
 outline.
- Fall back to direct/template output on any synthesis failure.

### Tests

- two specialist results become one coherent ordered response;
- canonical claim/citation relationships remain intact;
- unknown claim, citation, warning, disagreement, or result references fail;
- removed warning, hidden disagreement, or elevated status fails;
- invented action receipt fails;
- synthesis has no registry/provider execution access;
- local model unavailable, timeout, cancellation, and malformed draft all use
 safe fallback; and
- default role bindings report the same profile, and rebinding one role changes
 only that role's effective identity.

### Exit gate

V3-SYN-001, V3-SYN-002, and all V3-CONFIG-001 acceptance criteria pass.

## 10. Phase 8 — Replanning, recovery, and provenance

### Work

- Implement typed `ReplanPolicy` with a compiled maximum of one attempt.
- Add revision/parent lineage and completed-step reuse rules.
- Permit safe same-contract provider substitution.
- Add conservative startup reconciliation for nonterminal plans.
- Add plan/step/result/synthesis views and redacted trace events.
- Add CLI command rendering through the shared application API only.

### Tests

- one approved provider substitution;
- second attempt rejected;
- consent denial, cancellation, hard limit, or uncertain action never replans;
- completed external operation is not duplicated;
- restart with pending, local-running, hosted-running, and uncertain-action steps;
- provenance links original/revised plans and contributing evidence; and
- traces redact prompts, payloads, credentials, chain-of-thought, and provider
 bodies across every interface.

### Exit gate

V3-REPLAN-001 and V3-OBS-001 pass, including representative restart and
migration scenarios.

## 11. Phase 9 — End-to-end verification and closure

**Status:** Implemented, verified, and closed 2026-08-16. See
[PHASE_9_VERIFICATION.md](PHASE_9_VERIFICATION.md) and
[V3_CLOSURE.md](V3_CLOSURE.md).

### Required scenarios

1. Local-only answer with planner and deterministic fallback variants.
2. One specialist followed by direct output.
3. Research followed by one specialist and local synthesis.
4. Research feeding two parallel distinct specialists and local synthesis.
5. One optional branch fails and produces an honest partial response.
6. Mandatory research failure prevents dependent execution.
7. Specialists disagree and the final result preserves disagreement.
8. Per-step consent pauses and resumes the correct plan revision.
9. Cancellation during parallel work prevents every new start.
10. One safe replan and one rejected second replan.
11. Synthesis failure preserves completed work via deterministic fallback.
12. Schema-v6 migration and conservative nonterminal-plan recovery.

### Quality gates

- Full unit, contract, integration, adversarial, migration, security, and
 interface-parity suites pass.
- Repeated concurrency/cancellation stress passes without duplicate dispatch.
- Ruff passes across source and tests.
- Strict MyPy passes across source.
- Python compilation and `git diff --check` pass.
- Static boundaries prove that models cannot authorize, dispatch, mutate plans,
 or access provider-resolution policy.
- No generic planner/validator/scheduler branch contains optional capability IDs.
- Configuration contains exactly one validated binding for each local-model
 role, with all identities sourced from the named profile catalog.
- Limited live Ollama planner/synthesis and hosted-capability verification is
 recorded separately with dates, versions, and observed results.

### Closure rule

Deterministic gates and every non-deferred requirement must pass. Any missing
live verification or owner-only acceptance must be explicitly recorded as an
exception; it must not be silently marked successful. The owner alone records
V3 completion and closure.

## 12. Requirement traceability

| Requirement | Primary phases |
|---|---|
| V3-ROUTE-001 | 2, 3 |
| V3-ROUTE-002 | 2, 5 |
| V3-CONFIG-001 | 1, 2, 7 |
| V3-PLAN-001 | 3 |
| V3-PLAN-002 | 4 |
| V3-PLAN-003 | 3, 6 |
| V3-EXEC-001 | 4, 5 |
| V3-EXEC-002 | 5 |
| V3-SYN-001 | 7 |
| V3-SYN-002 | 6, 7 |
| V3-RES-001 | 4, 6 |
| V3-REPLAN-001 | 8 |
| V3-OBS-001 | 3, 8 |

## 13. Completion checklist

- [x] V3 requirement scope approved or explicitly deferred.
- [x] Named local-model profiles and independent role bindings implemented and migrated.
- [x] Versioned proposal and planner contracts implemented.
- [x] Pure DAG and redundancy validation implemented.
- [x] Additive schema-v7 migration verified.
- [x] Bounded scheduler and dependency propagation implemented.
- [x] Per-step authorization and typed result validation implemented.
- [x] Status aggregation and deterministic finalizers implemented.
- [x] Evidence-bounded local synthesis and fallback implemented.
- [x] One-attempt replanning and conservative recovery implemented.
- [x] Safe plan provenance and interface parity implemented.
- [x] All deterministic and static quality gates pass.
- [x] Limited live verification recorded; hosted verification explicitly deferred.
- [x] Owner acceptance recorded through the 2026-08-16 closure request.

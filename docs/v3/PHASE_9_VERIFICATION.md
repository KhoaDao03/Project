# Elly V3 Phase 9 Verification

**Verification date:** 2026-08-16; independently repeated after closure  
**Verdict:** Pass, with hosted live-provider verification explicitly deferred  
**Scope:** V3 requirements, implementation Phases 0–8, end-to-end integration,
and Phase 9 closure gates

## Outcome

All 13 V3 requirements have deterministic implementation and test evidence. The
audit found and resolved the principal end-to-end gap: the planner, plan builder,
scheduler, and synthesizer existed but the normal public submission path still
bypassed them. Public submissions now use the V3 workflow when a planner is
configured, while direct legacy test/embedding construction remains compatible.

The audit also resolved exact authorization resume. Consent or action
confirmation now pauses new plan work, persists the pause, exposes the proposal
through the shared API, and resumes the exact step on the same plan revision.
Authorization-capable steps are serialized at the pause boundary so a singular
public proposal cannot orphan another parallel authorization request.

## Blocking findings resolved

1. Connected local interpretation, typed proposal validation, persisted DAG
   construction, bounded execution, finalization, and conversation persistence
   through `Application.submit`.
2. Propagated consent and action-confirmation proposals through plan execution.
3. Added persisted same-revision authorization resume and task-ID plan
   cancellation.
4. Preserved deterministic V2.5 fallback behavior and resolved follow-up context
   when the configured fake planner cannot semantically interpret a request.
5. Added Phase 9 public-path tests for planner-to-capability execution and exact
   consent resume.
6. Cleared all Ruff and strict-MyPy findings discovered during the full audit.
7. Tightened Ollama planner schemas for safe identifiers/reason codes after live
   verification found malformed free-form output.
8. Made the Ollama synthesis schema request-specific so model output can only
   reference approved result, claim, citation, warning, and disagreement IDs.
9. The repeat audit fixed step-scoped freshness validation so a static
   specialist may consume current upstream research without itself claiming a
   current-information capability.
10. Raised the default plan-wide timeout from 120 to 180 seconds, matching the
    required research → specialist → synthesis critical path at the default
    60-second per-step ceiling.
11. Added actual shared-public-API tests for the one- and two-specialist
    research/synthesis workflows; the two-specialist test uses a barrier to
    prove concurrent execution.

## Required scenario evidence

| # | Scenario | Evidence | Result |
|---:|---|---|---|
| 1 | Local-only planner and deterministic fallback | `test_v3_phase2_local_planner` local/fallback cases; full legacy routing suite | Pass |
| 2 | One specialist, direct output | `test_v3_phase9_end_to_end.ComposedWorkflowTests.test_public_submission_runs_planner_validated_plan_and_capability` | Pass |
| 3 | Research → specialist → synthesis | `test_research_then_specialist_runs_through_local_synthesis` | Pass |
| 4 | Research → two parallel specialists → synthesis | `test_research_feeds_two_specialists_then_local_synthesis` with a concurrency barrier | Pass |
| 5 | Optional failure produces honest partial | `test_optional_failure_keeps_independent_work_and_returns_partial`; partial template test | Pass |
| 6 | Mandatory research failure prevents dependent work | `test_mandatory_failure_skips_descendant` | Pass |
| 7 | Disagreement is preserved | Phase 6 disagreement and Phase 7 synthesis-preservation tests | Pass |
| 8 | Consent pauses/resumes correct revision | `test_exact_consent_resumes_same_plan_revision` | Pass |
| 9 | Parallel cancellation prevents new starts | Phase 4 cancellation test plus 50 repeated stress runs | Pass |
| 10 | One safe replan; second rejected | Phase 8 replan policy and lineage tests | Pass |
| 11 | Synthesis failure preserves completed work | Phase 7 malformed/timeout/cancelled fallback test | Pass |
| 12 | Schema-v6 migration and conservative recovery | Phase 0/3 migration and Phase 8 recovery tests | Pass |

Scenarios 3 and 4 now execute end to end through the shared public application
API, planner validation, persisted DAG, scheduler, typed results, and local
synthesis. No test substitutes model authority for deterministic validation or
authorization.

## Requirement verification

| Requirement | Verdict | Primary evidence |
|---|---|---|
| V3-ROUTE-001 | Pass | Strict proposal codec, fake/recorded/live planner, clarification and fallback tests |
| V3-ROUTE-002 | Pass | Capability-first catalog validation and registry-only dispatch |
| V3-CONFIG-001 | Pass | Named profile, independent binding, precedence, migration, and redacted status tests |
| V3-PLAN-001 | Pass | Pure DAG, cycle, type-flow, limit, finalization, and persistence tests |
| V3-PLAN-002 | Pass | Bounded sequential/parallel scheduler, timeout, cancellation, and dependency tests |
| V3-PLAN-003 | Pass | Objective, perspective, redundancy, and verification-policy tests |
| V3-EXEC-001 | Pass | Per-step privacy, exact consent, action authorization, and derived-input tests |
| V3-EXEC-002 | Pass | Versioned result envelope, normalization, schema rejection, and receipt tests |
| V3-SYN-001 | Pass | Reference-bounded synthesis validation, live basic synthesis, and canonical rendering |
| V3-SYN-002 | Pass | Direct/template selection and deterministic synthesis fallback tests |
| V3-RES-001 | Pass | Status decision table, partial failure, cancellation, and disagreement tests |
| V3-REPLAN-001 | Pass | Single-attempt policy, reuse, safety rejection, and lineage tests |
| V3-OBS-001 | Pass | Redacted plan/result/synthesis views and interface-parity tests |

## Quality-gate evidence

- Full unit, contract, integration, adversarial, migration, security, and
  interface suite: **457 passed, 0 failed, 0 skipped**.
- Cancellation stress: **50/50 passed**.
- Parallel scheduling stress: **50/50 passed**.
- Ruff 0.16.3 across source and tests: pass.
- MyPy 1.19.1 `--strict` across **118 source files**: pass.
- Python compilation: pass.
- `git diff --check`: pass.
- Static inspection: generic planner, validator, scheduler, aggregation, and
  synthesis paths contain no optional capability IDs; provider resolution and
  authorization remain outside model ports/adapters.
- Local model profile validation: exactly one binding each for conversation,
  planner, and synthesis; all identities resolve through named profiles.

## Limited live verification

On 2026-08-16, local Ollama reported `qwen3:8b` (image ID prefix
`500a1f067a9f`) and `qwen3:14b` installed. Verification used the configured
`qwen3:8b` role:

- Planner: valid `local_only` proposal, reason `LOCAL_ONLY`, zero executable
  steps.
- Synthesis: valid `completed` draft with two distinct sections and no invented
  disagreement references.

Complex claim/citation/disagreement preservation remains covered by strict
deterministic adversarial tests; invalid live drafts fail closed and the plan
executor uses deterministic fallback.

Hosted research/specialist live verification was not run because hosted
credentials were unavailable. This is an explicitly recorded environment-bound
exception, not a successful hosted-provider claim. Fixture, contract, policy,
and interface-parity coverage passed.

## Residual risks

- Hosted provider behavior can change independently and should be smoke-tested
  when credentials are deliberately supplied.
- Exact authorization resume state is process-local, matching the existing
  in-memory consent authority. Restart recovery remains deliberately
  conservative and does not replay an uncertain external operation.

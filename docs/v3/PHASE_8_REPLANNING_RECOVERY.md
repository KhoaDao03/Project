# V3 Phase 8 — Replanning, Recovery, and Provenance

**Status:** Implemented and verified

Phase 8 closes the bounded replanning and observability requirements without
giving planner output authority over providers, payloads, consent, or actions.

## Implemented behavior

- `ReplanPolicy` accepts only typed triggers and permits at most one revision.
- Cancellation, denied authorization or consent, hard-limit exhaustion,
  uncertain external outcomes, unsafe idempotency, and scope expansion reject
  replanning with safe reason codes.
- `ReplanService` validates a caller-supplied revised proposal through the
  existing `PlanBuilder`, creates `revision=1` with `parent_plan_id`, and
  reuses only exact completed step contracts with retained artifacts.
- Same-contract provider substitution is represented by the existing
  capability/operation contract; provider selection remains in the live
  registry and execution-time authorization remains mandatory.
- Startup reconciliation lists pending/running plans. Local read-only active
  steps return to `PENDING`; external or consequential active steps become
  `INTERRUPTED` and are never automatically dispatched again.
- Recovery uses explicit recovery-only persistence operations, leaving normal
  state-transition rules strict and compare-and-set protected.
- Plan creation, transitions, results, synthesis, recovery, and replanning
  produce bounded plan events containing IDs, states, versions, counts, and
  reason codes only.
- Public plan views expose step timing/usage/result/evidence IDs and synthesis
  metadata. Trace views expose lineage and replacement IDs through the same
  application API used by the CLI.
- `/plan <plan-id>` and `/plan-trace <plan-id>` render only shared API views.

## Verification

`tests/test_v3_phase8_replan_recovery.py` covers one approved replan with
completed-artifact reuse, second-attempt and safety-gate rejection, local versus
external restart recovery, lineage, and trace redaction. Existing Phase 3–7,
API, and CLI suites remain green.

Phase 9 still owns end-to-end closure, live-provider verification boundaries,
and owner acceptance.

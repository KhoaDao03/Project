# V3 Phase 5 — Per-Step Authorization and Typed Results

**Status:** Implemented and verified

Phase 5 closes the authorization and result-contract boundary between the
validated Phase 4 plan scheduler and optional capability handlers.

## Implemented behavior

- The scheduler resolves declared input bindings immediately before dispatch.
  A result reused by a later step is rendered as application-owned text or
  bounded structured JSON; provider-native objects do not cross the capability
  boundary.
- The existing privacy policy classifies the complete resolved payload for
  every step. Derived output therefore receives a fresh classification before
  it can reach an external capability.
- Consent proposals and exact approvals are bound to task, plan, step,
  capability, operation, provider, model, purpose, payload digest, cost ceiling,
  and expiry. A one-step approval cannot authorize another step or provider.
- Consequential action confirmations retain the semantic action policy and now
  also carry plan/step scope. A completed consequential action must provide an
  application-verifiable receipt whose digest and capability/operation identity
  match the authorized action.
- `StepResultEnvelope` (`elly.step-result.v1`) is the provider-neutral typed
  result shape. It carries identity, status, summary/findings, claims and
  claim-to-evidence support, assumptions, uncertainties, warnings, structured
  output, presentation hints, provenance, usage, and safe failures.
- Legacy `TaskResult` capability responses are normalized at the application
  boundary for compatibility. Persisted legacy plan results are upgraded to
  the versioned envelope when first read. Unknown, old, malformed, mismatched,
  or unverifiable results become failed results and are not eligible as valid
  downstream output.
- Provider exceptions are converted to a provider-neutral failure result before
  they can reach the API or presentation layer. Claim support distinguishes
  absent evidence from contradictory evidence.

## Main implementation seams

- `src/elly/application/step_results.py` defines the envelope, safe JSON/result
  normalization, evidence states, usage metadata, and action receipts.
- `src/elly/application/capability_workflow.py` performs execution-time
  classification, consent/action binding, result normalization, and receipt
  verification.
- `src/elly/application/plan_executor.py` carries typed envelopes between
  dependency steps and exposes them alongside the legacy `TaskResult` view.
- `src/elly/adapters/sqlite_repository.py` stores the versioned envelope in the
  existing `step_results.result_json` column; no schema-version increment is
  required because the Phase 3 table already stores a versioned JSON payload.
- `src/elly/application/routing_contracts.py` and capability descriptors expose
  accepted input metadata and supported output-result schema versions.

## Verification

Targeted Phase 5 contract tests cover consent scope/expiry, derived-result
reclassification, local and provider failures, malformed/old/unknown schemas,
evidence absence versus contradiction, action receipt enforcement, envelope
persistence, and Phase 4 scheduler compatibility. The full repository gate is
required before claiming the phase complete.

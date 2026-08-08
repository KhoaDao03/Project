# M5 — Cloud Specialists, Routing, Privacy & Consent

**Status:** **Reopened by independent verification 2026-08-04.** Live specialist
execution passes after a repaired contract crash. Post-audit repairs now enforce
role scope, fail-closed privacy classification, normalized output truncation, and
distinct auth/model/quota/rate/timeout failures. Closure still depends on the M3
pricing input and aggregate M7 evidence.

## Implemented

- `SpecialistManifest` now declares role, model/prompt versions, privacy class,
  output ceiling, exclusions, and tool grants; research and coding manifests are
  discovered through the registry.
- Deterministic routing selects coding specialist, research specialist, web research,
  or local generalist. No specialist may authorize tools or recursive delegation.
- Privacy mapping is application-owned: `local` requires exact consent,
  `remote_allowed` may proceed only in `cloud_permitted`, `restricted` never leaves
  the process, and unclassified data fails closed.
- `ConsentWorkflow` creates redacted, expiring proposals and binds approval to the
  exact SHA-256 payload hash. Mutation, expiry, denial, and wrong proposal IDs cannot
  authorize a call.
- `FakeSpecialistProvider` proves deterministic success, malformed, truncation, and
  high-impact-action cases without network access.
- `OpenAISpecialistProvider` uses Responses Structured Outputs, `store:false`, no
  provider tools, configured model/prompt versions, and normalized typed results.
- CLI exposes `/approve <id>` and `/deny <id>` for one-time specialist consent.
- M3 guardrails wrap specialist calls; usage metadata and configured cost estimates
  are captured at the provider boundary.
- Role-mismatched or high-impact tasks are rejected before provider execution;
  unmarked payloads are unclassified and fail closed.

## Verification

- Strict deterministic suite: **124 passed, 0 failed**.
- Live smoke with public non-sensitive input returned a valid `known` SpecialistResult
  from `gpt-5.6-luna`; no provider tools were enabled.
- Compileall and `git diff --check` passed.

## Limitations

- Live usage is captured from the provider response; cost reconciliation uses the
  configured per-call estimate because authoritative billing prices are not hard-coded.
- Specialists do not execute files, shell commands, network tools, trades, or other
  high-impact actions. Parallel graphs, recursive delegation, finance specialization,
  and long-term memory remain deferred.

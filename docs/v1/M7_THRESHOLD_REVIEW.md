# M7 Interim Threshold Review — 2026-08-04

This is an interim review. It does not declare V1 releasable while required
quality and owner evidence remains incomplete.

Cloud reservation policy: `$0.01` per attempted remote call, `$10/month` ceiling,
with local Ollama at `$0`. This is a conservative fixed reservation based on the
provided `$0.20/$1.20` per-million-token input/output rates plus an allowance for
an unspecified tool-call fee.

Research claim-support policy is conservative: unsupported claims remain
`unknown`; citation URLs alone do not produce `known` results. Prototype backups
use the current basic authenticated envelope by owner decision, with vetted AEAD
deferred to a later version.

| Threshold | Current evidence | Result |
|---|---|---|
| Deterministic security/policy/schema/limits/contracts = 100% | 209/209 strict regression tests pass after unified conversational context, direct-market-source enforcement, source-bounding, and hosted-search reliability repairs | Pass for implemented scope; owner-controlled gaps remain in the V1 verification report |
| Fabricated citation/action-success events = 0 | Existing citation, consent, and status tests pass; live sample validated citations | Pass for tested scope |
| Routing ≥90%, 0 unauthorized cloud/tool calls | Deterministic routing/privacy tests exist; no M7 30-case routing aggregate yet | Pending |
| Citation support = 100% controlled fixtures | Citation validator tests pass; one live sample retained 1/2 citations | Pending full corpus |
| Required abstention/blocked = 100% | Existing blocked/unknown/security tests pass | Pass for tested scope; full EVAL mapping pending |
| Relevant evidence ≥90% | One live research query only | Pending |
| Concision average ≥4/5, no safety-critical <4 | Five qwen responses are non-empty; no owner rubric scores | Pending owner review |
| Hardware threshold | Five-prompt qwen3:8b re-confirmation, peak 10,649/16,376 MB VRAM; owner-approved development profile | Pass for approved development profile |
| Owner UAT | Owner review recorded 2026-08-07: clarity 4/5, control/privacy 3/5, usefulness 4/5, no safety-critical issue | Approved with UC-04, UC-06, UC-09, and UC-11 deferred to later versions |

## Decision

M7 is not complete. Owner UAT is now recorded with an approved scope deferral:
UC-04, UC-06, UC-09, and UC-11 are not verified for this version and will be
addressed later. Release status remains blocked by the pending aggregate quality
corpus and final release-threshold review.

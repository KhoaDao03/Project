# Version 1 Deferred Milestone Gaps

**Version:** Version 1 (M0–M7)  
**Status:** Deferred to later project iterations  
**Recorded:** 2026-08-07  
**Repository commit:** `28cf8d59554a51c75235f7e72e6ef94ba147844e`  
**Purpose:** record the reasons M3–M7 remain reopened or open, establish the safe deferred boundary, and prevent future agents from treating the current prototype as release-complete.

This document records scope deferrals and remaining evidence/production-hardening gaps. It does not change approved requirements, milestone statuses, release decisions, or owner decisions. The controlling status remains [V1_VERIFICATION_REPORT.md](V1_VERIFICATION_REPORT.md), supported by [MILESTONE_PLAN.md](MILESTONE_PLAN.md), [M7_RELEASE_CHECKLIST.md](M7_RELEASE_CHECKLIST.md), and [DECISIONS.md](DECISIONS.md).

## Current milestone disposition

- **M0–M2 — Closed.** Decision/contract work, the walking skeleton, and the real local Ollama path have recorded evidence.
- **M3–M6 — Reopened.** The implementation exists for the current prototype, but broader acceptance or production-hardening criteria remain unproven.
- **M7 — Open.** The deterministic harness exists, but aggregate quality evidence and final release-threshold review are incomplete.
- **Version 1 — Not release-ready.** These deferred items must not be reported as silently resolved.

## M3 — Guardrail Spine

**Cause of reopening:** the mechanics for shared request accounting, retries, timeouts, circuit behavior, limits, interruption, and conservative reservations are implemented and tested, but the cloud pricing/reservation policy is not backed by an authoritative provider price source.

**Deferred items:**

- Approve an authoritative nonzero cloud pricing and reservation policy.
- Confirm that the monthly budget and consent maximum represent meaningful billing protection.
- Re-run the complete M3 acceptance evidence after the pricing decision.
- Preserve independent accounting for retries and attempted remote calls.

**Safe current behavior:** use the configured conservative reservation; local Ollama is treated as zero-cost; fail closed when limits or budget are exceeded.

**Later-iteration acceptance:** pricing source, reservation policy, cost reconciliation, warning thresholds, and full M3 acceptance evidence are approved and recorded.

## M4 — Web Research, Evidence, and Epistemic Honesty

**Cause of reopening:** the hosted `web_search` path, freshness routing, citation validation, source selection, injection quarantine, and honest abstention are implemented. However, the complete aggregate quality corpus is missing, and provider annotations may contain source metadata without claim-supporting passages.

**Deferred items:**

- Execute and score the complete EVAL-001…030 research corpus.
- Complete aggregate routing, relevance, citation-support, freshness, abstention, conflict, and concision evidence.
- Decide whether the provider contract must supply claim-level passages for `known` results.
- Keep metadata-only provider summaries visibly `inferred`/unverified or `unknown`; never upgrade them silently.
- Reassess the hosted-provider policy if later requirements demand claim-level verification.

**Safe current behavior:** validate citation URLs, reject unsafe or unsuitable sources, preserve conflicts, and abstain when timely direct evidence cannot be established.

**Later-iteration acceptance:** the corpus is scored against the approved thresholds and the owner confirms whether the current metadata-only policy is sufficient.

## M5 — Cloud Specialists, Routing, Privacy, and Consent

**Cause of reopening:** specialist manifests, routing, Structured Outputs, scope checks, exact consent, secret handling, and tool/depth restrictions are implemented and tested, but aggregate acceptance evidence and pricing assurance remain incomplete. Some M5 capabilities were explicitly deferred from current-version UAT.

**Deferred items:**

- Complete aggregate specialist, privacy, consent, schema, failure, and execution-claim acceptance evidence.
- Reconfirm zero unauthorized cloud/tool calls across the full evaluation corpus.
- Preserve exact one-use consent bound to payload hash, provider, model, purpose, categories, expiry, and maximum reserved cost.
- Keep UC-04 privacy and consent outside current-version verification, per the owner-approved UAT decision.
- Do not expand specialist roles, recursive delegation, tools, or high-impact actions.

**Safe current behavior:** local-only remains the default; restricted and unclassified content fails closed; eligible private/local content requires exact consent; specialists cannot execute tools or external actions.

**Later-iteration acceptance:** the owner approves the complete privacy/specialist evidence and any future capability expansion separately.

## M6 — Data Controls and Operations

**Cause of reopening:** SQLite sessions, no-store behavior, profile controls, retention, redacted traces, source metadata, interruption recovery, and backup/restore mechanics are implemented. The backup envelope is a prototype rather than a vetted production AEAD/key-management solution, and recovery acceptance is incomplete. UC-06, UC-09, and UC-11 were deferred from current-version UAT.

**Deferred items:**

- Select and approve a vetted backup encryption/key-management design.
- Complete backup restore, corruption, recovery-time, and operational acceptance evidence.
- Complete current-version acceptance for startup continuity, profile/session controls, and trace/audit review in a later iteration.
- Preserve no-store, independent retention, profile confirmation, redaction, quarantine, and no automatic replay behavior.

**Safe current behavior:** treat the backup mechanism as prototype-only; do not claim production-grade cryptographic protection or recovery readiness.

**Later-iteration acceptance:** the owner approves the crypto/recovery design and the complete data-control UAT.

## M7 — Evaluation, Release Hardening, and UAT

**Cause of remaining open status:** the EVAL catalog and deterministic release gate are implemented, but aggregate provider-quality evidence, final threshold review, and complete current-version acceptance are incomplete.

**Deferred items:**

- Run and score all EVAL-001…030 cases with pinned provider/model/configuration evidence.
- Complete routing, evidence, citation-support, abstention, relevance, concision, safety, and hardware threshold review.
- Reconcile the recorded deterministic evidence counts with a clean authorized run.
- Carry owner-approved UC-04, UC-06, UC-09, and UC-11 deferrals explicitly rather than counting historical implementation tests as current-release verification.
- Reassess M3–M7 closure only after the remaining evidence and owner decisions are complete.

**Safe current behavior:** the release gate reports pending/blocked gates honestly and remains non-release-ready; deterministic test success alone does not close M7.

## Explicitly deferred capabilities

The following remain outside the current release boundary unless separately approved:

- Full page-body retrieval/RAG and local page reading.
- Semantic/vector memory.
- Web UI, voice, vision, crawling, and computer control.
- Portable trace export.
- Autonomous tools, shell/file writes, and high-impact actions.
- Parallel or recursive specialist graphs.
- Finance/stock specialist execution.
- Fine-tuned models.
- Production-grade backup cryptography and recovery operations.

## Rules for later iterations

1. Start from the authoritative status and decision documents.
2. Do not mark a deferred item complete based only on code existence or a fake-backed test.
3. Add acceptance tests and real-provider evidence for each reopened milestone.
4. Preserve the local-only default, privacy boundaries, exact consent, redaction, no-store behavior, URL safety, and application-owned authorization.
5. Update [TRACEABILITY.md](TRACEABILITY.md), [MILESTONE_PLAN.md](MILESTONE_PLAN.md), and the verification report when evidence changes.
6. Record owner decisions explicitly before changing scope, pricing, cryptography, provider permissions, or release status.
7. Reopen or close milestones only through an evidence-backed review; this document itself does not close them.

## Sources

- [REQUIREMENT.md](REQUIREMENT.md)
- [DECISIONS.md](DECISIONS.md)
- [MILESTONE_PLAN.md](MILESTONE_PLAN.md)
- [TRACEABILITY.md](TRACEABILITY.md)
- [TEST_SPECS.md](TEST_SPECS.md)
- [V1_VERIFICATION_REPORT.md](V1_VERIFICATION_REPORT.md)
- [M7_RELEASE_CHECKLIST.md](M7_RELEASE_CHECKLIST.md)
- [M7_THRESHOLD_REVIEW.md](M7_THRESHOLD_REVIEW.md)
- [M7_UAT_RECORD.md](M7_UAT_RECORD.md)

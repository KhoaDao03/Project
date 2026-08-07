# Version 1 Independent Verification Report

**Verification date:** 2026-08-04; qualified-summary follow-up 2026-08-05  
**Scope:** M0–M7 implementation, deterministic regression, live Ollama, bounded live
OpenAI smoke, security/privacy, documentation, and release readiness.  
**Decision:** **Not release-ready: blocking implementation gaps and missing quality/UAT evidence.**

## 1. Executive summary

M0, M1, and M2 may remain closed. M3, M4, M5, and M6 remain reopened because their
approved exit criteria are broader than the code and tests presently prove. M7
remains open. The integrated local Ollama path works with the configured
`qwen3:8b`; unavailable-service, missing-model, output-ceiling, and timeout paths
map honestly. A real coding-specialist call works after repair. Hosted research
returns validated citation metadata, but the provider does not expose enough
claim-level evidence for the application to call its answer `known`. The owner
selected the current-provider policy: Elly returns a clearly labeled `inferred`
provider summary with zero verified claims (or `unknown` for conflicts) rather
than inventing support.

An owner-independent remediation pass subsequently closed the shared-accounting,
specialist-policy, retention/scheduling, health, trace-display, and deterministic
evidence-selection defects. The deterministic suite passes, but a green suite is not a V1 release decision.
Aggregate quality thresholds and owner UC-01…UC-12 UAT were still absent at the
2026-08-04 verification date; the owner UAT follow-up is recorded below.

Owner UAT follow-up (2026-08-07): the owner approved the current verdict with
clarity 4/5, control/privacy 3/5, usefulness 4/5, and no safety-critical issue.
UC-04, UC-06, UC-09, and UC-11 are deferred to later versions and are not treated
as verified in the current release. The remaining release-threshold evidence is
still required before M7 closure.

## 2. Initial repository state

`HEAD` was `095178d` (`feat(m3): complete milestone 3 implementation and
verification`). The worktree was already materially dirty before this audit:
tracked edits covered README/config/docs and M1–M3 source; M1–M3 status documents
were moved into `docs/implementStatus/`; M4–M7 source, tests, manifests, scripts,
and status documents were untracked. Those pre-existing changes were preserved.
No `AGENTS.md` or `CONTRIBUTING.md` exists in the repository.

## 3. Authority and materials inspected

Authority was applied in this order: `docs/REQUIREMENT.md` 1.0; recorded owner
decisions in `docs/DECISIONS.md`; approved exceptions such as DEC-OQ-07; frozen
contracts; design/acceptance tests; then milestone and implementation claims.
Inspected materials included README, pyproject/config/env templates, requirements,
design, contracts, decisions, threat model, test specs, milestone plan,
traceability, implementation guide, changelog, every milestone status/evidence
record, all source modules, all tests, release scripts, specialist manifests, git
status, and relevant history.

No hardware benchmark was performed in this pass. Existing owner-approved
qwen3:8b fit evidence was treated as historical evidence; this pass performed
functional timing only to prove bounded behavior. OpenAI checks used public,
synthetic text. No sensitive owner data was sent.

## 4. M0–M7 verification matrix

| Milestone | Implementation | Verification | Documentation | Owner review | Closure decision |
|---|---|---|---|---|---|
| M0 Decision/contract gate | Complete | Verified from records plus live provider availability | Sufficient | Recorded for decisions/plan | **Remain closed** |
| M1 Walking skeleton | Complete | Deterministic integration verified | Sufficient after synchronization | Recorded | **Remain closed** |
| M2 Real Ollama/local-only | Complete after cancellation repair | Real CLI success/failure/limit/timeout verified | Sufficient after synchronization | qwen3:8b approval recorded | **Remain closed** |
| M3 Guardrail spine | Partial pending pricing | Shared request ledger/retry/circuit/warnings pass; owner-approved nonzero cloud pricing absent | Corrected | Pricing input pending | **Reopened** |
| M4 Web/evidence | Implemented for selected metadata-only policy; aggregate acceptance pending | Deterministic selection and inferred-summary behavior pass; live hosted annotations may still lack claim passages | Corrected | Current-provider/inferred policy recorded | **Reopened pending aggregate evidence** |
| M5 Specialists/privacy | Implementation repaired | Scope/privacy/error/output fixtures pass; aggregate acceptance and pricing remain | Corrected | Aggregate review pending | **Reopened** |
| M6 Data/operations | Partial pending crypto/recovery | Retention/scheduler/health/trace tests pass; vetted AEAD and recovery acceptance remain | Corrected | Crypto choice pending | **Reopened** |
| M7 Release/UAT | Partial harness | Deterministic gate passes; quality pending; owner UAT follow-up records approved deferrals | Accurate after synchronization | Pending final threshold review | **Remain open** |

## 5. Confirmed repairs

| Defect | Class / milestones | Observed defect | Repair and evidence | Status |
|---|---|---|---|---|
| V1-001 | Test defect, M7 | Release evidence defaulted deterministic/hardware gates to pass without running tests. | Script now runs regression; library defaults are pending; regression test added. | Fixed |
| V1-002 | Major security, M2 | Prefix-only Ollama URL validation accepted user-info host confusion such as `127.0.0.1:port@remote`. | Parse and validate the exact HTTP origin in config and adapter; negative test added. | Fixed |
| V1-003 | Major security, M5 | Consent preview leaked values after secret labels; approvals were replayable and not bound to provider/model/purpose/cost. | Full-value redaction, exact metadata binding, and one-shot consumption; tests added. | Fixed |
| V1-004 | Major security, M4 | Credential-bearing and encoded-IP citation URLs could pass fixture-mode validation. | Reject URL credentials, nonstandard ports, direct/encoded IPs, and local/internal suffixes; tests added. | Fixed |
| V1-005 | Major privacy, M4/M5 | Owner-specific hosted-research queries could leave the machine under cloud mode without exact consent. | Restricted content blocks; local content gets an exact one-time proposal before research; CLI test added. | Fixed |
| V1-006 | Major limits, M2/M3 | Local Ollama requests used `max(generalist,specialist)` and therefore inherited the larger specialist ceiling. | Local orchestrator now uses only `generalist_max_output_tokens`; composition regression added. | Fixed |
| V1-007 | Major data, M4/M5 | Successful research/specialist assistant turns were not persisted, breaking subsequent context/history. | Persist validated assistant result; avoid duplicate user body on consent resume; integration tests added. | Fixed |
| V1-008 | Blocking integration, M5 | Real specialist completion crashed on nonexistent `TaskResult.sources`. | Use the contract field `citations`; live rerun and fake CLI regression pass. | Fixed |
| V1-009 | Blocking honesty, M4 | Tests fabricated claim bindings from bare URLs and marked arbitrary provider prose `known`. | Only exact safe cited passages support claims; metadata-only results can produce a sanitized, explicitly unverified `inferred` summary under the owner-selected policy, but never verified claims. | Fixed; claim-level `known` remains unavailable without cited passages |
| V1-010 | Major cancellation, M2/M3 | Timeout set a flag but left the Ollama stream blocked, delaying cleanup. | Active localhost response socket is shut down; partial cancellation mapping retained; contract and live timeout rerun pass. | Fixed |
| V1-011 | Major timeout, M3 | A longer tool timeout could exceed the configured total request timeout. | Per-call wait is capped by remaining total duration; boundary test added. | Fixed |
| V1-012 | Major privacy, M1/M6 | Audit detail was truncated but credential values could still be persisted. | Credential-value redaction occurs before durable write; canary test added. | Fixed |
| V1-013 | Major validation, M5 | Wrong-typed specialist fields were coerced to strings; false performed-action claims could pass. | Strict raw/type validation and performed-action rejection; tests added. | Fixed |
| V1-014 | Major audit/consent, M5/M6 | Cloud approval was not durably audited before a provider call. | CLI writes redacted approval metadata first; audit failure prevents the call; tests added. | Fixed |
| V1-023 | Major freshness/relevance, M4 | A successful financial search could select community posts or news recaps by lexical overlap, while identical retries exhausted the provider allowance. Retrieval time was incorrectly treated as sufficient freshness evidence. | Current market-value queries now require direct quote/index sources; hosted search is time-anchored and community-filtered; retries request citation repair; URL variants deduplicate; quote conflicts stay unknown. Deterministic regressions added. | Fixed for implemented hosted path; aggregate live-quality evidence remains pending |

## 6. Blocker-remediation status and residual gaps

| Defect | Classification | Requirements / evidence gap | Consequence |
|---|---|---|---|
| V1-015 | Blocking owner decision, M3/M5 | Retry attempts now reserve independently; request usage, remaining monthly budget, and 50/75/90 warnings are exposed. The default cloud-call price remains zero and no approved price source exists. | **Partial:** mechanics fixed; owner must approve pricing/reservation policy before the $10 ceiling is substantive. |
| V1-016 | Major defect, M3 | One request-scoped step/provider/retry/cost ledger is now passed through conversation, research, and specialist workflows; timeout retry requires cancellation and boundary regressions were added. | **Fixed for implemented routes.** |
| V1-017 | Accepted provider limitation / missing aggregate evidence, M4 | Deterministic relevance/reliability ranking, stale rejection, canonical deduplication, token packing, conflict abstention, and metadata-only inferred summaries are implemented. Live annotations may remain citation markers rather than claim passages. | **Policy resolved:** owner selected the current provider plus explicit `inferred`/unverified presentation. Aggregate M7 evidence remains pending; `known` still requires cited passages. |
| V1-018 | Major defect, M5 | Role scope is checked before calls; unclassified content fails closed; auth/model/quota/rate/timeout failures are distinct; fake/provider truncation is normalized. | **Fixed; aggregate M7 evidence still pending.** |
| V1-019 | Major defect, M6 | Independent session/evidence/audit retention and periodic maintenance/daily-backup checks are implemented. The backup still uses a custom envelope. | **Partial:** owner must approve a vetted AEAD/key-management dependency; recovery acceptance remains. |
| V1-020 | Major defect, M6 | Storage and audit now probe required schema; `/trace` renders redacted route/detail; successful and failed/cancelled routes record bounded duration and request-ledger metadata, with provider/model/prompt/tools/usage/cost where applicable. | **Fixed for implemented routes; aggregate M7 scoring remains.** |
| V1-021 | Missing evidence, M7 | No complete 30-case execution/scoring corpus; routing/evidence/citation/concision thresholds and owner UC-01…UC-12 UAT are pending. | M7 and V1 release are blocked. |
| V1-022 | Documentation/test defect, M3–M6 | Prior status reports equated narrow or fake-backed tests with complete acceptance coverage; M6/M7 records dated 2026-08-05 are future-dated relative to this 2026-08-04 audit. | Those claims are not independent evidence of closure. |

## 7. Real-provider results

### Ollama

- Executable/service: `/usr/local/bin/ollama`, client and service `0.32.5`.
- Configured endpoint: `http://127.0.0.1:11434`; configured model: `qwen3:8b`.
- Installed models observed: `qwen3:8b`, `qwen3:14b`; 14B was not invoked.
- Real CLI success: synthetic prompt returned nonempty `integration verified`,
  `Evidence: inferred`, `Route: local_generalist`; `/status` reported Ollama healthy.
- Four-token configuration: detailed-answer prompt returned the bounded fragment
  `Dependency Injection (DI`, proving the local ceiling was passed through.
- Unavailable endpoint `127.0.0.1:9`: typed blocked result, no fallback.
- Missing model `elly-model-that-does-not-exist`: distinct typed blocked result.
- Tiny timeout (`tool=0.001 s`, `total=0.01 s`): typed blocked timeout; after repair,
  whole command completed in approximately 0.37 s including startup/shutdown.
- Prompts were synthetic. Audit logs displayed no prompt/model content or secret.

### OpenAI

- Bounded public hosted-search call reached the configured `gpt-5.6-luna` path and
  produced an application-validated official `python.org` citation. Because the
  annotation did not supply claim text. Under the later DEC-M4-02 policy, this
  path returns a sanitized `Evidence: inferred` provider summary, explicitly says
  verified facts are absent, and retains only validated source links.
- Bounded public coding-specialist call returned a valid structured answer from
  the configured provider after V1-008 was fixed. No provider tools were enabled.
- Live provider quality thresholds were not inferred from these two smokes.

## 8. Security and privacy assessment

Confirmed positive controls include local-only default routing, exact localhost
Ollama origin validation, `store:false` on OpenAI requests, no provider tools for
specialists, application-owned route/consent checks, one-shot exact consent,
restricted-content denial, URL/citation filtering, no-store message bodies,
redacted audit metadata, depth-one specialist tasks, and no shell/file/action
execution surface.

Release-blocking assurance gaps remain in authoritative cost pricing/accounting,
aggregate hosted-research quality evidence, vetted backup encryption,
and full AT-10/AT-13 end-to-end canary coverage. No dependency vulnerability
scanner applies to runtime dependencies because V1 uses the Python standard
library only; Python/toolchain provenance still remains an operator concern.

## 9. Commands and observed results

| Command | Result |
|---|---|
| `git status --short`; `git log --oneline -12`; `rg --files` | Initial state recorded; pre-existing dirty M4–M7 work identified. |
| `PYTHONPATH=src python3 -W error::ResourceWarning -m unittest discover -s tests -t .` | Baseline sandbox: 129 run, one socket setup error; authorized rerun: **135/135 pass**. |
| Focused repaired suites | Staged owner-independent blocker sets: **94/94** and final trace subset **83/83** pass. |
| `PYTHONPATH=src python3 scripts/run_release_gate.py --output /tmp/elly-v1-market-freshness-evidence.json --hardware-status pass` | **209/209 pass** after unified conversational context, direct-market-source enforcement, source-bounding, and hosted-search reliability repairs; 30 records, deterministic pass, quality pending, owner UAT scope decision recorded separately, hardware pass from explicit prior evidence, releasable false; exit 2 as designed. |
| `PYTHONPATH=src python3 -m compileall -q src tests` | Pass. |
| `git diff --check` | Pass. |
| `ruff check src tests` | Not run: `ruff` not installed. |
| `mypy src` | Not run: `mypy` not installed. |
| Ollama version/tags diagnostics | Pass; service 0.32.5, approved models present. |
| Real CLI Ollama success/output-limit/unavailable/missing-model/timeout commands | Pass after V1-010 repair. |
| Real CLI hosted research | Integration pass; claim-support gate correctly `unknown`. |
| Real CLI coding specialist | Initial crash (V1-008); repaired rerun pass. |

Final strict full-suite result after unified conversational-context and hosted-
research repairs: **203 passed, 0 failed, 0 skipped**.

## 10. Coverage and release decision

The source/test mapping in `docs/TRACEABILITY.md` remains useful at symbol level,
but its old “Implemented + Tested” labels did not prove every acceptance clause.
This report is the controlling independent closure assessment until the gaps above
are resolved and the traceability rows are expanded to individual acceptance cases.

**Technically verified:** No, not for the full approved V1 requirements. The local
core and several integrations are technically verified; V1 as a whole is partial.

**Owner-reviewed:** M0–M2 decisions/evidence have recorded owner review. Full V1
owner UAT is not recorded.

**Release-ready:** **No.** Blocking owner decisions (V1-015 and V1-019) and missing
release evidence (V1-021) remain. OQ-10 is an accepted pre-production deferral and
does not itself block the personal prototype build.

## 11. Exact next actions

1. Decide and configure a conservative nonzero cloud pricing/reservation policy;
   shared per-task mechanics are already implemented.
2. Retain the selected honest `inferred`/unverified hosted-research policy and
   complete aggregate AT-06/07/08 and M7 quality evidence. Upgrade the provider
   contract later only if claim-level `known` answers are required.
3. Approve a vetted backup AEAD/key-management dependency and complete recovery
   acceptance evidence.
4. Run and score all EVAL-001…030 cases at approved thresholds.
5. Rerun the release gate and independently reassess M3–M7 closure, carrying the
   owner-approved UC-04/06/09/11 deferrals as explicit scope exclusions for this
   version.

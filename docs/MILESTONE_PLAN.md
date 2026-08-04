# Elly Research Assistant — Version 1 Implementation Milestone Plan

**Document title:** Version 1 Implementation Milestone Plan
**Document version:** 0.1
**Status:** Finalized
**Date:** 2026-08-03
**Prepared for:** Project owner (Khoa Dao)
**Prepared in role:** Technical lead / product / architecture / test strategy / security / mentor (planning only)

> **This document is a proposed implementation sequence. It does not modify the approved requirements, architecture, or Version 1 scope. Milestones remain non-authoritative until approved by the project owner.**

---

## 1. Authoritative Source Documents

This plan is derived from, and subordinate to, the following documents. Where they disagree with this plan, they win.

| Source | Version / Status | Role in this plan |
|---|---|---|
| `docs/requirements.md` — Software Requirements Specification | 1.0, Baseline candidate | **Authoritative** for V1 requirement IDs, scope, non-goals, acceptance criteria, open questions, decisions. |
| `docs/designs.md` — Use-Case, Acceptance-Test, Architecture & Interface Design | 0.1, Architecture baseline **candidate** (mostly *provisional*) | Basis for component/contract structure and acceptance suites (AT-01…AT-15, EVAL-001…030). **Provisional**, pending owner approval of its ADRs and OQ answers. |
| `README.md` | Placeholder ("Elly") | No content bearing on planning. |

No `AGENTS.md`/`CONTRIBUTING.md` and no source code or tests exist yet. Product naming is inconsistent across the SRS ("Personal AI Assistant" / "Jarvis Research Assistant" / "Elly"); this plan uses **Elly** per the design document (see Assumption A-07).

---

## 2. Version 1 Milestone Strategy

Elly V1 is a **local-first, single-user, deterministic-orchestrator** text assistant with two prompt-defined cloud specialists, on-demand web evidence, strict epistemic honesty, and hard resource/privacy guardrails. The dominant risks are **not** feature breadth — they are (a) whether the local model fits the owner's hardware, (b) whether the chosen cloud model/web provider are actually available and behave as assumed, and (c) whether the safety spine (deterministic authorization, limits, privacy/consent, non-fabrication, SSRF/injection defense) is provably enforced by *application code*, not model goodwill.

The strategy therefore is:

1. **Gate first, build second.** Close the SRS's own pre-architecture gate (OQ-01…OQ-07), validate feasibility on real hardware/accounts, and freeze the versioned contracts before writing production code. The SRS explicitly withholds milestone commitment until this gate passes (SRS §28.5).
2. **Walking skeleton before real providers.** Prove the end-to-end architecture (CLI → deterministic orchestrator → ports → storage → audit) against **deterministic fakes** so the boundaries and contracts are validated before any external variability enters.
3. **Vertical slices that cross real boundaries**, each producing observable CLI behavior — not isolated technical layers.
4. **Safety spine early.** Limits, retry/circuit, failure/partial handling, and the privacy/consent boundary land *before* the external calls they protect.
5. **Fakes → live, in that order,** for every external dependency (Ollama, OpenAI, Brave/web). Live integration is a labeled phase inside the milestone that needs it, gated by the deterministic tests passing first.
6. **No premature capability.** No RAG vector store, long-term/semantic memory, multi-specialist graphs, crawling, voice/vision, or autonomous background work — all are Future scope (SRS §6.3, §27) and appear only in §18 (deferred).
7. **Testing, security, documentation, traceability, and owner-learning in every milestone**, not deferred to the end.

**Proposed count: 8 milestones (M0–M7).** M0 is a non-code decision/feasibility/contract gate the documents already require; M1–M7 are build milestones. This count is a proposal (see §15/§16), not a confirmed decision.

---

## 3. Planning Principles Applied

- Each milestone has one coherent objective and a demonstrable CLI outcome or concrete evidence artifact.
- Foundational tooling is introduced only when the first slice that needs it arrives (repo/test harness in M0–M1; async engine in M1–M2; cost port in M3; etc.).
- Deterministic fakes stand in for Ollama, OpenAI, and Brave/web until the milestone that explicitly makes each live.
- Interfaces/placeholders/fakes are **never** counted as completing the corresponding production capability; the coverage matrix distinguishes *initial / partial / full / verified*.
- Confirmed architectural decisions (ADR-004 orchestrator-as-deterministic-state-machine; the confirmed constraints in SRS §8.3 — Ollama local generalist, one configurable OpenAI provider, application-enforced policy, replaceable providers, delegation depth one, RAG-is-not-truth) are respected. All *provisional* ADRs are treated as labeled assumptions requiring owner approval (§15).
- Security and privacy work is placed at the boundary it protects (SSRF/injection in the web milestone; consent/secrets in the cloud milestone; redaction throughout).

---

## 4. Proposed Milestone Summary

| # | Name | One-sentence outcome |
|---|---|---|
| **M0** | Decision, Feasibility & Contract-Freeze Gate | Owner decisions (OQ-01…07) recorded, hardware/model + OpenAI + web feasibility validated, versioned contracts and threat model frozen, AT/EVAL suites turned into test specs — with **no production code**. |
| **M1** | Walking Skeleton: Deterministic Local Conversation | A terminal user holds a multi-turn conversation answered by a **deterministic fake generalist** through the real orchestrator, with structured status output, session persistence/no-store, health, and correlated audit. |
| **M2** | Real Local Generalist (Ollama) & Local-Only Operation | Real Ollama multi-turn conversation in enforced `local_only` mode on the owner's benchmarked hardware, with cancellation and no silent cloud fallback. |
| **M3** | Guardrail Spine: Limits, Retry/Circuit, Failure & Cancellation | All hard resource limits, timeout/retry/backoff/circuit-breaking, typed failure/partial handling, and restart-interruption are enforced deterministically and demonstrable via CLI limit/cancel/failure scenarios. |
| **M4** | Web Research, Evidence & Epistemic Honesty | Current-information questions produce claim-linked citations or honest `unknown`/`blocked`, proven first against **web fixtures** (RAG, SSRF, injection, conflict) then a small **live Brave** smoke. |
| **M5** | Cloud Specialists, Routing, Privacy & Consent | Research and coding specialists run through one configurable OpenAI adapter under exact privacy/consent control and depth-one routing, proven with a **fake provider** then a **live OpenAI** smoke. |
| **M6** | Memory, Data Controls & Operations | Confirmed profile, startup continuity, review/correct/delete, retention/expiry, full audit, cost monitoring, health, and backup/restore/rollback all work and are owner-controllable. |
| **M7** | Release Hardening, Evaluation Suite & UAT | The permanent 30-case evaluation suite, full security/AT-15 release gates, owner UAT of UC-01…UC-12, documentation, and final traceability pass at approved thresholds. |

---

## 5. Detailed Milestone Definitions

> Legend for scope: **Initial** = first scaffolding/contract; **Partial** = some acceptance criteria met; **Full** = all acceptance criteria met; **Verify** = acceptance evidence produced. "Fake" = deterministic in-process test double; "Live" = real external service.

---

### Milestone 0 — Decision, Feasibility & Contract-Freeze Gate

- **Number / Name:** M0 — Decision, Feasibility & Contract-Freeze Gate
- **Status:** **Complete (2026-08-04)** — decisions recorded + artifacts owner-accepted; **OpenAI/`web_search` feasibility validated** (RSK-02 retired). One check **deferred**: NFR-003 hardware benchmark → M2 (RSK-01 carried).
- **Outcome (one sentence):** Every pre-architecture owner decision is recorded, feasibility is validated on the real machine/accounts, and the versioned contracts, threat model, and test specifications are frozen — before any production code exists.

#### Objective
Close the gate the source documents themselves require. The SRS (§28.5) withholds architecture and milestone commitment until OQ-01…OQ-07 are answered and local-model/cloud-model/web feasibility is validated; the design (§11–12) lists the same prerequisites. This milestone reduces the two highest-impact risks (RSK-01 hardware fit, RSK-02 cloud-model access) *before* they can invalidate downstream milestones, and it converts provisional architecture choices into either owner-approved decisions or explicitly-labeled assumptions. **You learn** what your hardware can actually run, what the cloud/web providers actually offer, and how to express behavior as versioned contracts and tests before code.

#### User-visible or demonstrable outcome
- A completed **decision record** (SRS §23 extended) resolving OQ-01…OQ-07 and recording OQ-08/09 target values.
- A **hardware/model benchmark report** on the owner's WSL2 machine for 2–3 candidate quantized Ollama models (load time, time-to-first-token, throughput, peak RAM/VRAM, stability) — satisfies AT-15.1/.2 evidence and NFR-003 *initial*.
- **Feasibility smoke evidence**: the exact OpenAI model ID accessed with a Structured Outputs round-trip (`store:false`); a Brave Search + page-read round-trip confirming plan/terms/content-type handling.
- **Frozen versioned contract schemas** (as documents/JSON Schema, not wired code): `TaskRequest`/`TaskResult`, three-axis status, evidence object, claim support, specialist manifest + `SpecialistResult`, consent proposal/approval, context manifest, error taxonomy, provider ports.
- A **threat model** covering prompt injection, SSRF, secrets, cloud disclosure, logs, malicious model output (SRS §26 recommends this before web retrieval).
- **Executable test specifications** for AT-01…AT-15 and EVAL-001…EVAL-030 (as pending/skipped specs and fixtures).

#### Included scope
- Use cases: none implemented; UC-01…UC-12 mapped to suites.
- Requirements touched: NFR-003 *initial*, NFR-004 *initial* (fixture authoring), OQ-01…OQ-09 resolution; contract inputs for **all** downstream requirements.
- Architecture: confirm/approve ADR-001…016; freeze ports (§6.7) and contracts (§6.2–6.6) of the design.
- Security controls: threat model authored; no runtime controls yet.
- Documentation: decision record, benchmark report, feasibility notes, threat model, frozen contract catalog, test-spec index.

#### Explicitly deferred scope
- All production code, repository scaffolding, dependency installation, and any adapter wiring (deferred to M1+).
- Live integrations beyond a one-shot feasibility smoke (deferred to M2/M4/M5).
- OQ-10 (production threat/legal/incident scope) — needed only before production (SRS §25.3), not for V1 build.

#### Dependencies
- Earlier milestones: none.
- Owner decisions: **OQ-01…OQ-07 (blocking)**, OQ-08/OQ-09 target values.
- External services: owner's target machine; OpenAI account/credentials; Brave account/plan.
- Test data: initial EVAL/AT fixtures (recorded search results, fixture pages, canary secrets).

#### Implementation approach
No production code. Produce documents, schemas, fixtures, and a throwaway benchmark/smoke harness (clearly labeled non-production). Keep provider IDs, prices, and limits as **configuration values**, never domain logic. Freeze contracts as the stable seam so later provider swaps stay at the adapter boundary.

#### Verification strategy
- Manual: owner approves the decision record and thresholds.
- Evidence: benchmark report meets or revises NFR-003 targets; feasibility smokes pass; contract schemas reviewed; threat model reviewed.
- Traceability: contract catalog cross-references requirement IDs; test-spec index maps every AT/EVAL to a pending spec.

#### Entry criteria
- Requirements 1.0 and Design 0.1 are the current baselines; owner is available to decide OQ-01…07.

#### Exit criteria
- [x] OQ-01…OQ-09 have recorded owner decisions (`docs/DECISIONS.md`).
- [~] NFR-003 benchmark — **deferred to M2 by owner** (2026-08-04); not required to close M0. **RSK-01 carried** (local-model fit unvalidated until M2).
- [x] OpenAI/`web_search` smoke — **validated 2026-08-04** (`scripts/openai_smoke.py`): `store:false` + `web_search` + Structured Outputs succeeded on `gpt-5.6-terra`; account exposes terra/luna/sol. Brave dropped (hosted web_search, DEC-OQ-07). **RSK-02 retired.**
- [x] Versioned contract schemas + error taxonomy frozen (`docs/CONTRACTS.md`) — owner-accepted.
- [x] Threat model authored (`docs/THREAT_MODEL.md`) — owner-accepted.
- [x] AT-01…AT-15 and EVAL-001…030 exist as pending test specs with fixtures (`docs/TEST_SPECS.md`).

> **M0 closure note (2026-08-04):** decisions + specs complete; the OpenAI/`web_search`
> feasibility smoke **passed** (RSK-02 retired). The only deferred item is the NFR-003
> hardware benchmark (`[~]`) → M2; **RSK-01 (local-model fit) remains open** until then.

#### Risks and mitigations
- **RSK-01 (hardware fit):** benchmark now; if no candidate passes, revise targets/model before committing architecture capacity.
- **RSK-02 (cloud model access):** validate the exact ID now; fall back to an approved compatible model via configuration.
- **RSK-08 (web provider terms/cost):** confirm plan/storage/terms before designing retention (informs ADR-011/013).

#### Learning allocation
- **Owner implements with guidance:** decision record, threat model, contract freeze (these encode the product's core judgments; owning them is high learning value).
- **Pair implementation:** benchmark + feasibility smokes (learn provider realities together).
- **Agent implements:** fixture boilerplate and test-spec scaffolding.

---

### Milestone 1 — Walking Skeleton: Deterministic Local Conversation

- **Number / Name:** M1 — Walking Skeleton (Deterministic Local Conversation)
- **Status:** **Complete (2026-08-04)** — implemented, 77 tests passing, owner-reviewed. Fake-backed by design (real Ollama = M2); AT-15 "Verified" is M7.
- **Outcome:** A terminal user holds a multi-turn conversation answered by a **deterministic fake generalist** flowing through the real deterministic orchestrator, with structured status output, session persistence/no-store, health/status, and a correlated audit trail.

#### Objective
Validate the entire architectural spine end-to-end with zero external variability. This is the earliest possible architectural-risk reduction: it proves ports/adapters, the deterministic task state machine, the three-axis status contract, context building, storage transactions, and audit correlation all compose before a real model can mask design defects. **You learn** the orchestration control flow and the contract seams that make provider replacement possible (NFR-006) — the conceptual heart of the system.

#### User-visible or demonstrable outcome
From the terminal: type text → receive a structured response (Outcome, Evidence-state, Route=local) produced by a fake model; empty/whitespace/oversized input is rejected **before** any model call; `/new [--no-store]` starts a clean session; a later turn references an earlier in-session fact; a new session does not inherit transient facts; `/status` shows application/storage/(fake) model health; `/help` lists commands; every task emits a correlated audit record retrievable by task ID.

#### Included scope
- Use cases: UC-01 *partial* (deterministic path), UC-10 *initial* (`/status`).
- Requirements: FR-001 *initial→full (text surface)*, FR-002 *initial*, BUS-001 *initial*, AI-002 *initial* (deterministic routing to `local_generalist`, model output as non-authoritative proposal), AI-006 *initial* (P0/P1 context builder + manifest), AI-010 *initial* (status axes present), DATA-001 *partial* (session store + no-store), DATA-004 *initial* (audit event skeleton), OPS-001 *initial*, OPS-002 *initial*, SEC-007 *initial* (redaction baseline), UX-001 *initial* (response layout), NFR-006 *initial* (ports/adapters seam), AI-015 *initial* (config-declared capability).
- Architecture: Presentation (CLI), Application (`ConversationService`, `TaskService`), Domain (task/epistemic/validation state machines, context priority), Ports (`GeneralistPort`, `RepositoryPort`, `AuditPort`, `ClockPort`), Adapters (**fake** generalist, SQLite repo + migrations, log/metrics, env config).
- Security: input validation (size/Unicode/command), redaction baseline, "questions never authorize actions" seam.
- Documentation: developer README (run/build/test), architecture-as-built notes for the skeleton.

#### Explicitly deferred scope
- Real Ollama (fake only — M2), all cloud/web (M4/M5), limits/retry/circuit framework (M3), profile/retention/backup (M6), streaming (optional; deferred).
- The fake generalist is a **test double**, not the AI-001 capability.

#### Dependencies
- M0 frozen contracts and decisions; approved provisional architecture (ADR-002/003/006/016).
- Test data: deterministic fake-model response fixtures.

#### Implementation approach
Thin vertical slice CLI→orchestrator→port→SQLite→audit. Implement the domain state machines and contracts exactly as frozen in M0. The generalist is behind `GeneralistPort` with a deterministic fake adapter so the same contract tests (AT-03.5, AT-02.4-style swap) will later accept the Ollama adapter unchanged. Reserve output tokens and record the context manifest even with the fake, so "minimum sufficient context" is observable from day one.

#### Verification strategy
- Unit: state machines, context ranking/exclusion, input validation, redaction.
- Contract: fake generalist obeys `GeneralistPort`.
- Integration: SQLite transactions/migrations, session persistence vs no-store, audit correlation.
- Acceptance: AT-01.1–.5, AT-03.5 (adapter substitution), AT-13.5 (no chain-of-thought) *partial*.
- Manual demo: the flow above.

#### Entry criteria
- [ ] M0 exit criteria met; contracts frozen; owner approved provisional architecture.

#### Exit criteria
- [x] Multi-turn conversation via CLI returns a complete `TaskResult` contract with three-axis status from the fake generalist.
- [x] Empty/oversized input rejected with no model call (AT-01.2/.3).
- [x] In-session reference works; new session does not inherit transient facts (AT-01.4/.5). *(Context assembly + isolation tested; true reference resolution needs the real model, M2.)*
- [x] No-store leaves no message body; stored session reloads (AT-01, DATA-001 partial).
- [x] `/status` and `/help` work; audit records share one correlation ID; no secrets/chain-of-thought in logs.
- [x] Replacing the fake adapter with another conforming fake requires no domain/application change (AT-03.5).

#### Risks and mitigations
- **Over-engineering the skeleton:** cap scope to P0/P1 context and the fake model; defer ranking/eviction depth to M4.
- **Contract drift:** treat M0-frozen schemas as source of truth; any change is a change-controlled decision.

#### Learning allocation
- **Owner implements with guidance:** deterministic orchestrator / task state machine (core domain logic — highest learning value).
- **Pair implementation:** context builder + manifest; response contract composition.
- **Agent implements:** CLI plumbing, SQLite repository + migration runner, logging adapter, fake generalist double.

---

### Milestone 2 — Real Local Generalist (Ollama) & Local-Only Operation

- **Number / Name:** M2 — Real Local Generalist & Local-Only Operation
- **Status:** **Complete (2026-08-04)** — qwen3:8b owner-approved for development/testing; cancellation and CLI evidence passed. qwen3:14b remains explicit opt-in.
- **Outcome:** Real Ollama multi-turn conversation in enforced `local_only` mode on the benchmarked machine, with cancellation, honest degradation, and provably no silent cloud fallback.

#### Objective
Turn the skeleton into a genuinely useful local assistant and validate the confirmed local-first constraint on real hardware. It reduces the residual half of RSK-01 (does the chosen model behave acceptably in the real loop, not just in a benchmark). **You learn** the Ollama adapter boundary, cancellation semantics, and how local-only mode is *enforced* rather than merely defaulted.

#### User-visible or demonstrable outcome
Real local conversation with the benchmarked model; `/cancel` (or Ctrl+C) stops an in-progress generation and shows verified partial work; with the network disabled the assistant still answers ordinary requests; a missing/stopped Ollama or absent model returns a distinct typed `blocked` status and **never** calls cloud; swapping to another compatible Ollama model is a configuration change only.

#### Included scope
- Use cases: UC-01 *full*, UC-07 *initial* (local cancellation).
- Requirements: AI-001 *full*, API-001 *full*, BUS-002 *full*, FR-002 *full*, FR-001 *full* (cancellation input), FR-005 *initial* (local task cancel), FR-006 *initial* (local failure/partial), AI-014 *partial* (`local_only` path + no silent fallback), NFR-003 *full* (benchmark targets met on target machine), AI-019/NFR-001 *partial* (local concurrency, queue, local-call timeout), NFR-002 *partial* (local timeout/one bounded retry), OPS-002 *partial* (Ollama/model health).
- Architecture: real Ollama HTTP adapter behind `GeneralistPort`; async engine with bounded local semaphore + small in-process queue + cooperative cancellation (ADR-005, local subset).
- Security: local-only enforcement point (fail-closed against cloud when mode is local_only or ambiguous).
- Documentation: Ollama setup/runbook; benchmark results appended.

#### Explicitly deferred scope
- Cloud/web (M4/M5); full limit matrix and circuit breaker (M3); cost tracking (M3/M5). Cloud fallback remains **absent by construction** — there is nothing to fall back to yet, and the guard is asserted.

#### Dependencies
- M1 skeleton; M0 approved model ID + hardware targets; Ollama installed in WSL2.

#### Implementation approach
Replace the fake generalist with the real adapter, reusing M1's `GeneralistPort` contract tests to prove substitutability (AT-02.4). Wire cancellation through the task engine. Enforce local_only in the domain policy (not the adapter). Keep timeouts/queue from Section 7 provisional defaults as configuration.

#### Verification strategy
- Contract: Ollama adapter passes the same `GeneralistPort` suite (healthy/unavailable/missing-model/timeout/malformed → distinct typed errors) (AT-05-style for local; AT-02.3).
- Integration: cancellation stops scheduling and preserves partial work (AT-01.6).
- Acceptance: AT-02.1–.4; NFR-003 gate via AT-15.1/.2.
- Manual: network-disabled demo; model-swap demo.

#### Entry criteria
- [x] M1 complete; qwen3:8b benchmark evidence and owner approval recorded (M0/NFR-003/DEC-M2-03).

#### Exit criteria
- [x] Real adapter answers through development default `qwen3:8b`; qwen3:14b is explicit opt-in (AT-15.1/.2 partial; final release evaluation remains M7).
- [x] Local-only composition uses no cloud/search path; Ollama health and adapter contract are verified (AT-02.1/.2).
- [x] Missing Ollama/model maps to a distinct typed error; no fallback path exists (AT-02.3).
- [x] Model swap is configuration-only; fake and HTTP adapter contract tests pass (AT-02.4).
- [x] Cooperative cancellation maps to `CANCELLED`, preserves streamed partial work, and emits cancellation evidence (AT-01.6).

#### Risks and mitigations
- **RSK-01 residual:** if real-loop performance disappoints, downsize/quantize or revise targets by owner decision (configuration-driven).
- **Cancellation races:** cooperative cancellation token checked before each scheduled step; ignore late results.

#### Learning allocation
- **Owner implements with guidance:** local-only enforcement + no-silent-fallback policy (security-sensitive decision).
- **Pair implementation:** cancellation flow through the async engine.
- **Agent implements:** Ollama HTTP adapter, health probes, runbook.

---

### Milestone 3 — Guardrail Spine: Limits, Retry/Circuit, Failure & Cancellation

- **Number / Name:** M3 — Guardrail Spine
- **Status:** **Complete (2026-08-04)** — guardrails, retry/circuit, fake cost, timeout/cancellation, and restart interruption implemented and tested.
- **Outcome:** All configurable hard limits, timeout/retry/backoff/circuit-breaking, typed failure/partial handling, cost-reservation scaffolding, and restart-interruption are enforced deterministically and demonstrable through CLI limit, cancel, and failure-injection scenarios.

#### Objective
Build the safety spine that must exist **before** external, costly, or attackable calls. This is deliberate risk-first sequencing: RSK-07 (cost/retry runaway) and the crash-prevention guardrails are addressed while the only real provider is local and free, so the framework is proven cheaply. **You learn** how the application — not the model — owns limits, backpressure, and failure classification (a core owner-learning goal: tool permissions and resource guardrails).

#### User-visible or demonstrable outcome
With low test limits configured, an operation that would exceed any ceiling (calls, tokens, queue, concurrency, duration, or configured monthly cost budget) is refused with a typed limit event and preserved partial work; boundary tests (one below/at/above) pass; concurrent racers never exceed an atomic ceiling; repeated fake-provider failures open a circuit; an application restart marks in-flight tasks `interrupted` and replays nothing; failure injected at each boundary names the component and never emits global success. The monthly budget is authoritative for M3; a separate daily budget is not introduced.

#### Included scope
- Use cases: UC-07 *full*, UC-08 *full*.
- Requirements: AI-019 *full*, NFR-001 *full* (atomic reservations, boundary/concurrency), NFR-002 *full* (timeout/retry/backoff+jitter/circuit), FR-005 *full*, FR-006 *full* (error taxonomy, partial results, fail-closed to `blocked`), OPS-003 *initial* (cost reserve/reconcile with **fake** pricing), OPS-004 *partial* (interrupted-task marking, no auto-replay).
- Architecture: `CostPort` (fake pricing), limit/reservation domain service, retry/circuit policy in adapter-support layer, restart reconciliation in `TaskService`.
- Security: fail-closed on invalid/missing external limits (SEC/NFR intersection); no secret exposure in limit errors.
- Documentation: limits/config reference (Section 7 baseline), failure taxonomy guide.

#### Explicitly deferred scope
- Real cloud cost/pricing (M5 makes OPS-003 full with live usage); backup/restore/migration rollback (M6 completes OPS-004).
- Circuit/retry are proven against **fake** failing providers here; live provider behavior is smoke-tested in M4/M5.

#### Dependencies
- M2 (async engine, local cancellation) and M1 (task state machine, audit).

#### Implementation approach
Centralize limits as a domain reservation service consulted before every resource allocation; make ceilings atomic where concurrency applies. Implement the full error taxonomy (§6.8) and route each class to retry/no-retry/partial/blocked. Drive circuit-breaker and retry tests with deterministic failing fakes. Cost reservation uses configured (fake) price data and fails conservatively when pricing is missing.

#### Verification strategy
- Unit: each limit at −1/at/+1 boundary; error-class mapping; cost reservation math.
- Integration: atomic concurrency race; circuit opens at threshold; restart reconciliation; failure injection at each adapter (AT-14.1).
- Acceptance: AT-11.1–.7, AT-14.1/.3.
- Manual: low-limit CLI demo; kill-and-restart demo.

#### Entry criteria
- [x] M2 complete; error taxonomy frozen (M0).

#### Exit criteria
- [x] Every implemented M3 local/provider limit enforced with boundary + atomic concurrency tests passing (AT-11.1/.2).
- [x] Transient-only retry with bounded backoff/jitter; permanent/unknown never auto-retry; circuit opens on repeated failure (AT-11.3/.4).
- [x] Budget reserved before and reconciled after a (fake-priced) call; over-budget call prevented (AT-11.5/.6).
- [x] Invalid/missing limits fail closed and disable startup capability (AT-11.7).
- [x] Restart marks active tasks `interrupted` with zero automatic external replays (AT-14.3).
- [x] Failure/cancellation boundaries name the component, preserve received partial work where available, and emit no global success (AT-14.1).

#### Risks and mitigations
- **Layer-in-isolation smell:** demonstrate through UC-07/UC-08 CLI behavior, not just unit tests.
- **Config invalidity at runtime:** validate limits at startup (OPS-002) and fail closed.

#### Learning allocation
- **Owner implements with guidance:** limit reservation + fail-closed policy; retry/circuit policy (security- and cost-sensitive core).
- **Pair implementation:** error taxonomy → status mapping; restart reconciliation.
- **Agent implements:** cost-port fake, backoff/jitter utility, failure-injection test doubles.

---

### Milestone 4 — Web Research, Evidence & Epistemic Honesty

- **Number / Name:** M4 — Web Research, Evidence & Epistemic Honesty
- **Status:** Proposed
- **Outcome:** Current-information questions produce claim-linked citations or an honest `unknown`/`blocked`, proven first entirely against **web fixtures** (RAG, SSRF, prompt injection, conflict, freshness) and then confirmed with a small **live Brave + page-reader** smoke.

#### Objective
Deliver the research value proposition and, more importantly, prove the two hardest correctness/safety areas — RAG grounding (RSK-04: relevant-looking but false/stale content) and untrusted-web defense (RSK-05: SSRF/prompt injection) — under fully deterministic conditions before any live network variability. This is the milestone where epistemic honesty becomes real (evidence-driven `known/inferred/unknown/blocked`). **You learn** retrieval ranking, claim-to-evidence binding, and why the application treats page content as data, never instructions.

#### User-visible or demonstrable outcome
Ask a current-information question → the freshness detector routes to research → search + selected-page reads (fixtures) → evidence objects with provenance/freshness → minimum-sufficient evidence selected, duplicates collapsed, conflicts preserved → local generalist synthesizes → material claims bind to evidence IDs → response shows Outcome, Evidence-state, Route=web, numbered clickable Sources, or an honest `unknown`/`blocked`; a fixture page instructing "ignore policy / reveal keys / call a tool" changes nothing; loopback/private/encoded/redirect-to-private URLs are blocked; oversized/unsupported content never becomes evidence. Then: a live Brave query returns real citations in a smoke run.

#### Included scope
- Use cases: UC-02 *full*, UC-05 *full*.
- Requirements: FR-003 *full*, FR-004 *full*, DATA-003 *full*, AI-009 *full*, AI-006 *full* (P2/P3/P4 evidence ranking + eviction), AI-010 *full*, AI-011 *full*, AI-012 *full*, UX-001 *full* (citations/status), API-003 *full*, API-004 *initial* (web integration declaration), SEC-003 *full*, SEC-006 *full*, SEC-004 *initial* (Brave API key handling), AI-005 *initial* (local-vs-research routing), NFR-002/OPS-003 *applied* to web calls.
- Architecture: `SearchPort`, `PageReaderPort`, `ContentExtractorPort`; query planner, source selector, URL guard (DNS/IP validation + redirect re-check), passage ranker, claim validator; Brave + safe HTTP reader adapters (live phase).
- Security: SSRF guard, injection quarantine, HTTPS-only policy, content-type/size limits, secret handling for the search key.
- Documentation: retrieval/claim-validation design as-built; web-safety runbook.

#### Explicitly deferred scope
- Cloud specialist synthesis of evidence (M5 adds the research **specialist**; here the **local** generalist synthesizes). Crawling, vector/semantic retrieval, long-term memory — Future (deferred).
- Live web is a **smoke** phase only; deterministic release gates use recorded fixtures (design §8.1).

#### Dependencies
- M3 guardrails (page/byte/time limits, retry/circuit for web); M0 web feasibility + threat model; Brave account/plan.
- Test data: fixture search results, fixture pages (allowed HTML, private-IP, redirect-to-private, oversized, unsupported-type, conflicting, stale, injection).

#### Implementation approach
Build and prove the entire pipeline against fixtures first (deterministic 100%-gate security/RAG tests), then swap in live Brave + reader behind the unchanged ports for a small smoke suite. Citations render only from stored provenance — never model-produced URLs. Evidence with missing URL/retrieval-time cannot be cited. Preserve conflicts; weak retrieval → insufficient-evidence status, never a pressured answer.

#### Verification strategy
- Unit: URL policy, source-class ranking, dedup, freshness, passage scoring, claim-support classification, redaction of page content.
- Contract: search/reader/extractor ports (success + each failure class).
- Integration: full research pipeline on fixtures; live Brave smoke.
- Security: AT-10.1–.4 (injection, SSRF, redirect, oversized/type).
- Acceptance: AT-06 (all), AT-07 (all), AT-08 (all).
- Manual: current-question demo + injection/SSRF demo.

#### Entry criteria
- [ ] M3 complete; threat model + web feasibility approved (M0).

#### Exit criteria
- [ ] Current questions trigger retrieval; timeless questions avoid unnecessary web calls at the approved routing threshold (AT-06.1).
- [ ] Ten successful current-question fixtures carry claim-linked citations to actually-retrieved pages; model-invented URLs rejected (AT-06.2/.3).
- [ ] Primary sources outrank comparable secondary; duplicates collapse without erasing conflicts (AT-06.4/.5); unreadable/disallowed sources are named, not cited (AT-06.6).
- [ ] Context/RAG rules hold: P0/P1 preserved, secrets/expired/duplicates excluded, freshness only when time-sensitive, weak retrieval → insufficient-evidence (AT-07 all).
- [ ] Epistemic rubric holds across strong/indirect/absent/conflicting/failed evidence; suggestions separated; injected success claims removed (AT-08 all).
- [ ] Injection, SSRF, redirect-to-private, oversized/unsupported all blocked (AT-10.1–.4).
- [ ] Live Brave + reader smoke returns real cited evidence.

#### Risks and mitigations
- **RSK-04 (false/stale RAG):** primary-source ranking, freshness, claim binding, abstention — all fixture-gated at 100% before live.
- **RSK-05 (injection/SSRF):** deterministic authorization outside prompts; hostile-fixture red-team gate.
- **RSK-08 (provider):** ports isolate Brave; live is smoke-only so provider changes don't break deterministic gates.

#### Learning allocation
- **Owner implements with guidance:** claim validator + epistemic classification; URL/SSRF guard; injection handling (the trust-critical domain logic and security decisions).
- **Pair implementation:** passage ranker / minimum-sufficient evidence selection.
- **Agent implements:** Brave/reader/extractor adapters, fixture corpus, provenance rendering.

---

### Milestone 5 — Cloud Specialists, Routing, Privacy & Consent

- **Number / Name:** M5 — Cloud Specialists, Routing, Privacy & Consent
- **Status:** Proposed
- **Outcome:** Research and coding specialists run through one configurable OpenAI adapter under exact privacy classification, exact consent, secret protection, and depth-one routing — proven with a **fake specialist provider** first, then a small **live OpenAI** smoke.

#### Objective
Complete the specialist/extensibility experiment and the cloud privacy boundary — the second-most safety-critical area (RSK-06 unexpected disclosure, RSK-05 authorization). It lands after the guardrail spine and web evidence so cloud calls inherit limits, cost control, and evidence handling. **You learn** routing/task decomposition, the exact-consent lifecycle, secrets handling, and the specialist manifest/registry that makes new specialists addable without touching the core (BUS-003).

#### User-visible or demonstrable outcome
A coding request routes to the coding specialist; a research question can escalate to the research specialist over M4 evidence; a request with owner-specific/private content shows an exact consent view (provider, model, purpose, categories, bounded preview, max cost) and makes **no** call until approved; changing the payload after approval invalidates it (hash mismatch); `local_only` makes no cloud call; a specialist asking to call another specialist/tool is rejected (depth one); an adversarial model proposal to make an unauthorized call executes nothing and is logged; registering a conforming test specialist needs no existing-code change; a live OpenAI smoke returns a valid `SpecialistResult` with `store:false` and no provider tools.

#### Included scope
- Use cases: UC-03 *full*, UC-04 *full*, UC-12 *full*.
- Requirements: AI-003 *full*, AI-004 *full*, API-002 *full*, AI-007 *full*, AI-008 *full*, AI-005 *full* (local/research/coding/clarification routing), AI-013 *full*, AI-014 *full* (`cloud_permitted` + consent), AI-015 *full* (manifest declarations), AI-002 *full* (deterministic authorization of cloud calls), BUS-003 *full*, BUS-001 *full* (all three journeys now real), API-004 *full*, SEC-001 *full*, SEC-002 *full*, SEC-004 *full*, SEC-005 *full*, OPS-003 *full* (live usage/cost reconcile).
- Architecture: `SpecialistProviderPort`, OpenAI Responses adapter (Structured Outputs, `store:false`, no provider tools), `SpecialistWorkflow`, `ConsentWorkflow`, capability registry/manifest validator, privacy classifier.
- Security: privacy classification + minimization + exact consent + payload-hash binding; secrets resolved only at adapter boundary; high-impact/write actions rejected (disabled in V1).
- Documentation: specialist authoring guide; consent/privacy behavior; OpenAI adapter runbook.

#### Explicitly deferred scope
- Parallel/multi-specialist graphs, recursive delegation, finance specialist, fine-tuned models — Future (deferred). Optional high-impact second-pass verification (AI-016) — deferred.
- Live OpenAI is **smoke**; deterministic gates use the fake provider + recorded fixtures.

#### Dependencies
- M4 (evidence for research specialist), M3 (limits/cost/circuit), M0 (validated OpenAI model ID + consent policy OQ-06).
- Test data: fake specialist responses (valid, missing-field, wrong-type, free-prose, oversized), canary secrets, private/public payload fixtures.

#### Implementation approach
Prove routing, schema validation, depth-one, consent, and privacy against a **fake** `SpecialistProviderPort` (deterministic), then wire the live OpenAI adapter behind the same port for smoke. Consent binds to a payload hash with expiry; the adapter re-checks the outgoing hash before sending. Secrets never enter prompts/logs/exports. Manifests are validated before a specialist becomes routable; invalid manifests stay disabled.

#### Verification strategy
- Unit: routing rules, privacy classification, consent state machine, manifest validation, schema/scope/execution-claim validators.
- Contract: OpenAI adapter (configured ID, prompt/schema versions, `store:false`, timeout, output ceiling in request; each failure class → distinct error; ≤1 retry/repair) (AT-05 all).
- Integration: fake-provider full specialist flow; consent lifecycle; depth-one rejection; live OpenAI smoke.
- Security: AT-09 (all), AT-10.5/.6 (no high-impact action; canary secrets absent), AT-03.1–.4.
- Acceptance: AT-04 (all), AT-05 (all), AT-09 (all), AT-03 (all).
- Manual: consent-approve/deny/mutate demo; local-only-vs-cloud demo.

#### Entry criteria
- [ ] M4 complete; OpenAI model validated (M0); consent/privacy policy (OQ-06) approved.

#### Exit criteria
- [ ] Research/coding/unrelated requests route correctly at the approved threshold with 0 unauthorized cloud/tool calls (AT-04.1, AT-03.1).
- [ ] Each role refuses out-of-scope work; valid Structured Output passes, malformed does not (≤1 repair) (AT-04.2/.3, AT-05.4/.5).
- [ ] Output/evidence ceilings enforced; truncation → `partial`; assumptions/uncertainties visible (AT-04.4/.5).
- [ ] OpenAI request carries configured ID, `store:false`, no provider tools, versions, ceilings; failure classes distinct (AT-05.1–.6).
- [ ] `local_only` → no cloud call; public may proceed under `cloud_permitted`; owner-specific/private requires exact consent; denial/expiry/mutation → no call (AT-09 all).
- [ ] Depth-one enforced; adversarial proposals execute nothing and are logged (AT-03.2, AT-03.1).
- [ ] Conforming specialist registers without existing-code change; nonconforming rejected (AT-03.3/.4).
- [ ] Canary secrets absent from prompts/manifests/DB/logs/errors/traces/exports; high-impact prompts execute no action (AT-10.5/.6).
- [ ] Live OpenAI smoke returns a valid `SpecialistResult`; usage/cost reconcile within tolerance (OPS-003, AT-13.3).

#### Risks and mitigations
- **RSK-06 (disclosure):** default local-only, minimization, exact consent, hash binding; deterministic gates before live.
- **RSK-02/RSK-13 (model/provider drift):** configurable ID, versioned prompts/schemas, adapter isolation.
- **RSK-03 (specialist underperformance):** measured later in M7 eval; here the contract/limits are enforced.

#### Learning allocation
- **Owner implements with guidance:** routing, privacy classification, consent lifecycle, secrets handling, depth-one authorization (explicitly high-value: task routing, tool permissions, security-sensitive decisions).
- **Pair implementation:** specialist manifest/registry; result validation/synthesis.
- **Agent implements:** OpenAI Responses adapter, fake specialist provider, fixtures.

---

### Milestone 6 — Memory, Data Controls & Operations

- **Number / Name:** M6 — Memory, Data Controls & Operations
- **Status:** Proposed
- **Outcome:** Confirmed profile, startup continuity, review/correct/delete, retention/expiry, full audit, cost/health visibility, and backup/restore/rollback all work and are owner-controllable, with confirmed data kept strictly separate from inference.

#### Objective
Complete continuity and operability without over-reaching into semantic memory (explicitly Future). It addresses RSK-09 (memory stores wrong/sensitive inference) and RSK-10 (logs as a secondary sensitive store) and makes the system operable/recoverable. **You learn** intentional-memory design (confirmed vs inferred), retention/deletion semantics, and operational recovery.

#### User-visible or demonstrable outcome
`/profile add|list|correct|delete` manages explicitly confirmed items; inferred items never masquerade as confirmed; on startup only relevant confirmed, non-expired profile + versioned behavior load (secrets and full history do not); `/history list|open|delete` respects retention; no-store leaves no body after restart; a corrected item changes later context and a deleted item disappears from retrieval; corrupt memory is quarantined and base behavior still starts; `/trace <task-id>` and `/sources <task-id>` show redacted, correlated execution with model/prompt versions, sources, timing, usage/cost, approvals, errors — and no chain-of-thought; `/status` reports every capability's health and remaining budget; a backup/restore and a failed-migration rollback preserve integrity.

#### Included scope
- Use cases: UC-06 *full*, UC-09 *full*, UC-10 *full*, UC-11 *full*.
- Requirements: DATA-002 *full*, DATA-005 *full*, DATA-001 *full* (retention/expiry), DATA-004 *full* (complete audit fields + trace views), SEC-007 *full*, OPS-001 *full*, OPS-002 *full* (all dependency health), OPS-003 *full* (budget visibility), OPS-004 *full* (backup/restore/migration/rollback), AI-006 *reinforced* (profile in context), UX-001 *reinforced* (trace/sources presentation).
- Architecture: `MemoryService`, `TraceQueryService`, retention/expiry jobs, migration runner + rollback, backup/restore procedure, storage separation (config/profile/session/evidence/audit/secrets).
- Security: redaction completeness across all stores/exports; confirmed/inferred separation; tombstone-on-delete.
- Documentation: data-control guide; backup/restore + rollback runbook; retention policy.

#### Explicitly deferred scope
- Semantic/episodic long-term memory, vector retrieval, portable trace export (DATA-006 optional) — deferred.
- OQ-10 production incident scope — before production, not V1 build.

#### Dependencies
- M1–M5 (audit events, cost data, provider health to display); M0 OQ-08 retention/recovery targets.

#### Implementation approach
Store confirmed profile items with source/sensitivity/confirmation/expiry, strictly separated from model-derived inference. Deletion is transactional with a non-sensitive tombstone; partial deletion reports exact unaffected scope. Trace views assemble redacted events chronologically. Backups are owner-initiated + encrypted; migrations transactional with prior-version rollback; interrupted tasks (from M3) surface in trace.

#### Verification strategy
- Unit: profile confirmed/inferred separation; retention/expiry; redaction; trace assembly.
- Integration: correction→context change, deletion→retrieval absence, no-store across restart, corrupt-memory quarantine, backup/restore integrity, failed-migration rollback.
- Acceptance: AT-12 (all), AT-13 (all), AT-14.4/.5.
- Manual: profile/data-control demo; `/trace` and `/sources` demo; restore demo.

#### Entry criteria
- [ ] M5 complete (audit/cost/health data exist to expose); OQ-08 targets approved.

#### Exit criteria
- [ ] Confirmed items load; inferred never masquerade (AT-12.3); correction/deletion honored (AT-12.4); no-store leaves no body after restart (AT-12.1); stored sessions reload within retention and expire (AT-12.2); corrupt memory quarantined, base behavior starts (AT-12.5); partial deletion reports exact scope (AT-12.6).
- [ ] Full trace correlates route/providers/versions/sources/approvals/retries/timing/usage/cost/limits/final states; no chain-of-thought (AT-13.1/.5).
- [ ] `/status` reports healthy/degraded/disabled per capability without secrets (AT-13.2); usage/cost reconcile within tolerance (AT-13.3); audit-write failure visible and blocks consent-required calls without a durable approval (AT-13.4).
- [ ] Failed migration leaves prior schema usable; backup/restore meets the approved recovery objective with referential integrity (AT-14.4/.5).

#### Risks and mitigations
- **RSK-09:** confirmed/inferred separation + review/delete controls.
- **RSK-10:** redaction tests across every store/export; minimal metadata on uncertainty.

#### Learning allocation
- **Owner implements with guidance:** confirmed-vs-inferred memory model; retention/deletion semantics (important domain + privacy logic).
- **Pair implementation:** trace assembly + redaction; backup/restore/rollback procedure.
- **Agent implements:** migration runner, retention jobs, `/profile` `/history` `/trace` `/sources` command plumbing.

---

### Milestone 7 — Release Hardening, Evaluation Suite & UAT

- **Number / Name:** M7 — Release Hardening, Evaluation Suite & UAT
- **Status:** Proposed
- **Outcome:** The permanent 30-case evaluation suite, full security/AT-15 release gates, owner UAT of UC-01…UC-12, documentation, and final traceability all pass at approved thresholds, and V1 is demonstrable end-to-end.

#### Objective
Turn a feature-complete system into a **verified, releasable** one. It addresses RSK-03 (specialist quality, now measurable), RSK-11/12 (scope/schedule discipline), and closes the release gate. **You learn** how to evaluate an AI system against versioned fixtures and thresholds and how to make a release decision on evidence.

#### User-visible or demonstrable outcome
The full EVAL-001…030 suite runs and reports per-case results pinned to model/prompt/provider/fixture version/date; all deterministic safety/policy/contract tests pass 100%; approved probabilistic thresholds (routing ≥90% with 0 unauthorized calls, ≥90% relevant evidence, 100% citation support / required abstention, concision rubric ≥4/5) pass with failures individually visible; the owner completes UC-01…UC-12 UAT; documentation and the traceability matrix are complete.

#### Included scope
- Use cases: UC-01…UC-12 *verification* (UAT).
- Requirements: NFR-004 *full*, BUS-001…003 *verify*, and **verification** of every mandatory V1 requirement against its AT/EVAL; NFR-006 *final* (portability/contract tests across all adapters); UX-001 *verify*.
- Architecture: no new components; test harness, evaluation runner, release checklist.
- Security: complete red-team/security suite (AT-10 all) and 100% deterministic safety gate.
- Documentation: user guide, operator runbook, release notes, final SRS traceability update (design §9/Appendix A), decision-log closure.

#### Explicitly deferred scope
- All optional V1 items (streaming NFR-005, web UI UX-002, verification pass AI-016, trace export DATA-006) unless separately approved — remain out of the release unless the owner elects them.
- All Future roadmap items (§18).

#### Dependencies
- M1–M6 complete; OQ-09 thresholds approved; recorded fixtures + live smoke suites available.

#### Implementation approach
Assemble the permanent evaluation suite from EVAL fixtures; run deterministic assertions for safety/schema/limits and a human-reviewed rubric for answer quality (design §8.1). Keep recorded fixtures for deterministic gates plus a small live smoke to detect provider drift. Do not let aggregate scores hide individual safety failures. This milestone must **not** become a catch-all — every requirement already has an owning build milestone; M7 only *verifies* and hardens.

#### Verification strategy
- Full AT-01…AT-15 regression; EVAL-001…030; security red-team; performance/benchmark re-confirmation; owner UAT.
- Traceability: every mandatory requirement shows a passing verification with model/prompt/provider/date.

#### Entry criteria
- [ ] M1–M6 complete; OQ-09 thresholds approved; fixtures frozen.

#### Exit criteria (also the V1 Definition of Done — see §14)
- [ ] All deterministic security/policy/schema/limit/contract tests pass 100% (AT-15.4).
- [ ] All approved probabilistic thresholds met, failures individually visible (AT-15.5); 0 fabricated citation/action-success events.
- [ ] EVAL-001…030 recorded with model/prompt/provider/fixture/date (AT-15.3).
- [ ] Owner completes UC-01…UC-12 UAT and approves clarity, control, usefulness (AT-15.6).
- [ ] SRS §20 V1 acceptance checklist fully satisfied; traceability matrix updated; docs complete.

#### Risks and mitigations
- **RSK-03 (specialist quality):** if a role misses threshold, narrow the role or change model via configuration; do not weaken safety gates.
- **RSK-11/12 (scope/schedule):** reduce optional items, never safety/eval controls (SRS §26).

#### Learning allocation
- **Owner implements with guidance:** the evaluation rubric application and the release decision (core judgment).
- **Pair implementation:** eval runner + threshold reporting.
- **Agent implements:** regression harness wiring, fixture management, doc scaffolding.

---

## 6. Milestone Dependency Map

```
M0 (Gate: decisions, feasibility, contracts, threat model, test specs)
        │
        ▼
M1 (Walking skeleton: fake generalist, orchestrator, storage, audit, health)
        │
        ▼
M2 (Real Ollama + local-only + cancellation + hardware gate)
        │
        ▼
M3 (Guardrail spine: limits, retry/circuit, failure/partial, restart)
        │
        ▼
M4 (Web research + evidence + epistemic honesty; fixtures → live Brave smoke)
        │
        ▼
M5 (Cloud specialists + routing + privacy/consent; fake → live OpenAI smoke)
        │
        ▼
M6 (Memory, data controls, trace/health/cost, backup/restore/rollback)
        │
        ▼
M7 (Evaluation suite + security/AT-15 gates + UAT + hardening/release)
```

Key cross-links: M3 protects M4/M5 (limits/cost/circuit are prerequisites for external calls). M4 supplies evidence consumed by M5's research specialist. M5's audit/cost/health data is surfaced by M6's trace/status views. M7 verifies all prior milestones. The path is intentionally **linear** because the SRS assumes a single developer (§8.6, Assumption A-05); with added capacity, M3's guardrails and M4's web pipeline could partially overlap after M2.

---

## 7. Requirements Coverage Matrix

All 51 mandatory V1 requirements. "Introduces" = first real (non-fake) support begins; "Completes" = all acceptance criteria met; verification consolidated in M7.

| Req ID | Summary | Introduces | Completes | Verification method | Final expected status |
|---|---|---|---|---|---|
| BUS-001 | Trustworthy assistant core | M1 | M5 | AT-01/02/06; UAT | Verified |
| BUS-002 | Local-first operation | M2 | M2 | AT-02 | Verified |
| BUS-003 | Extensible specialists | M5 | M5 | AT-03/04 | Verified |
| FR-001 | Text interaction surface | M1 | M2 | AT-01 | Verified |
| FR-002 | Multi-turn session context | M1 | M2 | AT-01/07 | Verified |
| FR-003 | Freshness detection & research | M4 | M4 | AT-06 | Verified |
| FR-004 | Search/read/citations | M4 | M4 | AT-06 | Verified |
| FR-005 | Task cancellation | M2 | M3 | AT-01/14 | Verified |
| FR-006 | Failure/partial handling | M2 | M3 | AT-14 | Verified |
| DATA-001 | Session history/no-save | M1 | M6 | AT-12 | Verified |
| DATA-002 | Confirmed profile/startup | M6 | M6 | AT-12 | Verified |
| DATA-003 | Evidence/provenance records | M4 | M4 | AT-06/07 | Verified |
| DATA-004 | Execution/audit records | M1 | M6 | AT-13 | Verified |
| DATA-005 | Review/correct/delete/no-store | M6 | M6 | AT-12 | Verified |
| AI-001 | Configurable local generalist | M2 | M2 | AT-02/15 | Verified |
| AI-002 | Application-controlled orchestration | M1 | M5 | AT-03/10 | Verified |
| AI-003 | Research & coding roles | M5 | M5 | AT-04 | Verified |
| AI-004 | Configurable OpenAI provider | M5 | M5 | AT-05 | Verified |
| AI-005 | Bounded specialist routing | M4 | M5 | AT-04 | Verified |
| AI-006 | Minimum-sufficient context | M1 | M4 | AT-07 | Verified |
| AI-007 | Structured specialist results | M5 | M5 | AT-04/05 | Verified |
| AI-008 | Concise specialist output | M5 | M5 | AT-04 | Verified |
| AI-009 | Evidence-grounded RAG | M4 | M4 | AT-07 | Verified |
| AI-010 | known/inferred/unknown/blocked | M1 | M4 | AT-08 | Verified |
| AI-011 | Non-fabrication | M4 | M4 | AT-08 | Verified |
| AI-012 | Output validation/conflict | M4 | M4 | AT-08 | Verified |
| AI-013 | Delegation depth one | M5 | M5 | AT-03 | Verified |
| AI-014 | Cloud policy modes | M2 (local) | M5 (cloud+consent) | AT-09 | Verified |
| AI-015 | Model/prompt portability | M1 | M5 | AT-03/05 | Verified |
| AI-019 | Bounded model/tool use (limits) | M2 (local) | M3 | AT-11 | Verified |
| API-001 | Ollama integration | M2 | M2 | AT-02 | Verified |
| API-002 | OpenAI integration | M5 | M5 | AT-05 | Verified |
| API-003 | Web search/reader integration | M4 | M4 | AT-06/10 | Verified |
| API-004 | Integration fallback contract | M4 | M5 | AT-03/13 | Verified |
| SEC-001 | Local/cloud privacy boundary | M5 | M5 | AT-09 | Verified |
| SEC-002 | Consent for external sharing | M5 | M5 | AT-09 | Verified |
| SEC-003 | Untrusted content/injection | M4 | M4 | AT-10 | Verified |
| SEC-004 | Secrets management | M4 (search key) | M5 | AT-10 | Verified |
| SEC-005 | Least privilege/no high-impact | M1 | M5 | AT-03/10 | Verified |
| SEC-006 | Input/URL/retrieval safety (SSRF) | M4 | M4 | AT-10 | Verified |
| SEC-007 | Log minimization/redaction | M1 | M6 | AT-10/13 | Verified |
| NFR-001 | Configurable hard limits | M2 (local) | M3 | AT-11 | Verified |
| NFR-002 | Timeout/retry/backoff/circuit | M2 (local) | M3 | AT-11 | Verified |
| NFR-003 | Local hardware fit/perf budget | M0 (benchmark) | M2 | AT-15 | Verified |
| NFR-004 | Permanent evaluation suite | M0 (fixtures) | M7 | AT-15 | Verified |
| NFR-006 | Maintainability/portability | M1 | M7 | AT-03 | Verified |
| OPS-001 | Logging/metrics/tracing | M1 | M6 | AT-13 | Verified |
| OPS-002 | Config/health status | M1 | M6 | AT-13 | Verified |
| OPS-003 | Cost/usage monitoring | M3 (fake price) | M5 (live) | AT-13 | Verified |
| OPS-004 | Recovery/backup/rollback | M3 (interrupt) | M6 | AT-14 | Verified |
| UX-001 | Transparent user communication | M1 | M4 | AT-08 | Verified |

**Coverage check:** all 51 mandatory requirements are assigned an introducing and completing milestone; none is unassigned. Optional (AI-016, DATA-006, NFR-005, UX-002) and Future IDs are intentionally excluded (§18).

---

## 8. Use-Case & Acceptance-Test Coverage

| Use case | Responsible milestone(s) | Supporting requirements | Acceptance suites | Key dependencies |
|---|---|---|---|---|
| UC-01 Local conversation | M1 (fake) → M2 (real) | FR-001/002, BUS-002, AI-001/006/010, DATA-001/004 | AT-01, AT-02, AT-07, AT-13 | Ollama (M2) |
| UC-02 Current-information research | M4 | FR-003/004/006, AI-009/010/012, DATA-003, SEC-003/006 | AT-06, AT-07, AT-08, AT-10, AT-14 | Web fixtures→Brave; M3 limits |
| UC-03 Coding specialist | M5 | AI-003/004/005/007/008/013, API-002, SEC-005 | AT-03, AT-04, AT-05, AT-09 | OpenAI; M3 limits |
| UC-04 Cloud consent boundary | M5 | AI-014, SEC-001/002/004, DATA-004 | AT-09, AT-10, AT-13 | Privacy policy OQ-06 |
| UC-05 Unknown/conflicting evidence | M4 | AI-010/011/012, UX-001 | AT-08 | M4 evidence pipeline |
| UC-06 Startup continuity | M6 | DATA-001/002/005, AI-006, SEC-001 | AT-12, AT-13, AT-14 | M1–M5 data |
| UC-07 Cancel long-running task | M2 (initial) → M3 (full) | FR-005/006, NFR-001, OPS-001 | AT-01, AT-11, AT-14 | Async engine (M2) |
| UC-08 Limit reached | M3 | AI-019, NFR-001/002, OPS-003 | AT-11 | Guardrail spine |
| UC-09 Manage session/profile data | M6 | DATA-001/002/005, SEC-007 | AT-12 | M6 memory |
| UC-10 Inspect config/health | M1 (initial) → M6 (full) | OPS-002/003 | AT-13 | Provider health (M2/M4/M5) |
| UC-11 Review execution trace | M6 | DATA-004, OPS-001/003, SEC-007 | AT-10, AT-13 | Audit events (M1–M5) |
| UC-12 Register/replace specialist | M5 | BUS-003, AI-003/007/015, API-004, NFR-006 | AT-03, AT-04 | Specialist contract (M0) |

**Acceptance-suite → milestone map:** AT-01→M1/M2/M3 · AT-02→M2 · AT-03→M5 (with AT-03.5 first proven in M1) · AT-04/AT-05→M5 · AT-06/AT-07/AT-08→M4 · AT-09→M5 · AT-10→M4 (injection/SSRF/content) + M5 (high-impact/secrets) · AT-11→M3 · AT-12→M6 · AT-13→M6 (with initial in M1) · AT-14→M3 (fail/interrupt) + M6 (migration/backup) · AT-15→M7 (with NFR-003 benchmark in M0/M2). EVAL-001…030 are authored in M0 and run as the permanent suite in M7, exercised incrementally as each capability lands.

---

## 9. Risk-Reduction Rationale (Sequence Justification)

- **Architectural risk** is attacked first: M0 freezes contracts and M1 proves the whole spine with fakes, so a boundary defect surfaces before any provider can hide it.
- **Integration risk** is staged fake→live in every external milestone (M2 Ollama, M4 Brave, M5 OpenAI), so deterministic logic is proven before live variability (RSK-08/RSK-13).
- **Security/privacy risk** lands at the boundary it guards: SSRF/injection with the web pipeline (M4), consent/secrets/authorization with cloud (M5), redaction throughout — and each is 100%-gated on fixtures before live (RSK-05/RSK-06).
- **External-provider & cost risk** is bounded before external calls exist: the guardrail spine (M3) and the M0 feasibility gate precede M4/M5 (RSK-01/RSK-02/RSK-07).
- **Testing risk** is controlled by authoring AT/EVAL specs in M0 and verifying continuously; M7 verifies, it does not discover.
- **Learning complexity** rises gradually: deterministic conversation → real model → guardrails → evidence/RAG → cloud specialists/consent → memory/ops → evaluation, so each new concept builds on a proven base.
- **Cost risk** is near-zero until M5 (only local/free before that), and M5 inherits M3's hard cost ceilings and consent gates.

---

## 10. Version 1 Definition of Done

V1 is complete when **all** of the following hold (mirrors SRS §20 and design §8):

1. All 51 mandatory requirements reach *Verified* in the coverage matrix (§7).
2. Every deterministic security/policy/schema/limit/contract test passes **100%** (AT-15.4); 0 fabricated citation or action-success events.
3. All approved probabilistic thresholds (OQ-09) pass with failures individually visible (AT-15.5).
4. UC-01…UC-12 pass owner UAT; owner approves clarity, control, usefulness (AT-15.6).
5. Hardware/latency targets (NFR-003) pass on the target machine; EVAL-001…030 recorded with model/prompt/provider/fixture/date.
6. Security reviewed: injection, SSRF, secret-leakage, consent-binding, high-impact-denial suites pass (AT-10 all).
7. Documented: user guide, operator runbook, data-control + backup/restore runbooks, threat model, and updated traceability matrix.
8. Owner-reviewed: SRS §20 checklist satisfied; all blocking OQs have recorded decisions.
9. Ready for demonstration as a **personal local prototype** (not production/multi-user until OQ-10 is resolved).

---

## 11. Assumptions

Each is provisional and labeled; if the owner rejects it, the noted milestones/requirements are affected.

| ID | Assumption | Why introduced | Affects | If rejected |
|---|---|---|---|---|
| A-01 | The **provisional architecture** (ADR-001…016: Python modular monolith, CLI-first, SQLite/WAL, async in-process engine, ports/adapters, WSL2) is the basis for milestone structure. | Design 0.1 is a candidate; milestones need a concrete structure. | All milestones. | Re-sequence/re-scope M1–M6 to the revised architecture. |
| A-02 | **Section 7 provisional config defaults** are used as test/enforcement boundaries. | Limits/tests need numbers before benchmarks finalize them. | M2, M3, M4, M5. | Update limit fixtures/config; no structural change. |
| A-03 | **Three-axis status** (execution/epistemic/validation, ADR-016) is the result contract. | Distinguishes partial failure from honest uncertainty. | M1, M4, M5. | Revise `TaskResult`/`SpecialistResult` schemas in M0/M1. |
| A-04 | The **research specialist** synthesizes M4 evidence in M5; M4 itself uses the **local** generalist for synthesis. | Keeps M4 provider-free (fakes-first) and defers cloud to M5. | M4, M5. | Move some synthesis into M4 or add an interim cloud phase. |
| A-05 | **Single developer**, so milestones are linear. | SRS §8.6. | Whole schedule. | Allow M3/M4 partial overlap after M2. |
| A-06 | **Terminal-first (OQ-02)**, **local-only default (OQ-06/ADR-008)**. | Shortest path to validate core behaviors. | M1–M7. | Add web-UI work; adjust default-mode tests. |
| A-07 | Product name is **"Elly."** | SRS naming is inconsistent; design uses Elly. | Docs only. | Rename in docs. |
| A-08 | A **walking-skeleton fake-model milestone (M1)** precedes real Ollama. | Early architectural validation without provider risk. | M1. | Fold skeleton into M2 (loses early isolation). |

---

## 12. Recommendations Requiring Owner Approval

Not requirements unless separately accepted.

- **R-01 — Approve this 8-milestone sequence** (M0–M7) as the V1 build order. *Affects:* all. *Reject →* re-plan.
- **R-02 — Keep a dedicated M0 gate** (decisions + feasibility + contract freeze + threat model) before any code, per SRS §28.5/§26. *Reject →* feasibility risk moves into build milestones.
- **R-03 — Include the M1 walking skeleton with a fake generalist.** *Reject →* start at M2 with real Ollama (less architectural isolation).
- **R-04 — Author the threat model in M0, before web retrieval** (SRS §26). *Reject →* document it later at higher risk.
- **R-05 — Exclude all optional V1 items** (streaming NFR-005, web UI UX-002, verification pass AI-016, trace export DATA-006) from the active plan; add only by change control. *Reject →* insert into M2/M6/M5/M6 respectively with added scope.
- **R-06 — Treat live integrations as smoke-only in M2/M4/M5**, with deterministic fixtures as the release gate (design §8.1). *Reject →* redesign release gates around live services.

---

## 13. Blocking Questions

Milestone planning can proceed as a draft, but **build cannot start / cannot be finalized** until these are answered — consistent with the SRS's own readiness gate (§28.5). M0 exists to resolve them.

| # | Blocking question | Source | Blocks |
|---|---|---|---|
| BQ-1 | Approve the provisional **architecture baseline** (ADR-001…016) or direct revisions? | Design 0.1 is a candidate | Everything (A-01) |
| BQ-2 | **OQ-01** single-user boundary confirmed? | SRS §25.1 | M0, security/data scope |
| BQ-3 | **OQ-02** terminal vs web as required interface? | SRS §25.1 | M1 surface |
| BQ-4 | **OQ-03** hardware/model target + benchmark to run? | SRS §25.1 | M0/M2 (NFR-003) |
| BQ-5 | **OQ-04** exact OpenAI model ID + account capability? | SRS §25.1 | M0/M5 (RSK-02) |
| BQ-6 | **OQ-05** numeric limit/cost budgets (or adopt §7 baseline)? | SRS §25.1 | M3/M5 |
| BQ-7 | **OQ-06** cloud privacy policy / default mode / consent triggers? | SRS §25.1 | M4/M5 (SEC-001/002) |
| BQ-8 | **OQ-07** web provider + retrieval/robots/citation policy? | SRS §25.1 | M4 |
| BQ-9 | **OQ-08** storage/retention/recovery targets? (before M6) | SRS §25.2 | M6 |
| BQ-10 | **OQ-09** evaluation rubric + release thresholds? (before M7) | SRS §25.2 | M7 |

OQ-10 (production threat/legal/incident) is **not** a V1-build blocker; it gates production/sharing only (SRS §25.3).

---

## 14. Deferred Items (Not in Active V1 Milestones)

**Optional V1 (add only by owner-approved change control):** AI-016 high-impact verification pass · DATA-006 portable trace export · NFR-005 streaming responses · UX-002 simple web UI.

**Future / out of V1 (SRS §6.3, §27):** FR-101 focused crawler · DATA-101 long-term semantic/episodic memory · AI-101 parallel multi-specialist orchestration · FR-102 voice · FR-103 image/vision · AI-102 finance specialist · FR-104 controlled computer assistance · AI-103 fine-tuned/custom models · OPS-101 autonomous background tasks.

**Binding V1 exclusions (must remain unavailable):** background autonomy, general crawling, continuous sensing, arbitrary code execution, filesystem/shell access, email/purchase/trade/other external writes, recursive/swarm delegation, multi-user tenancy, semantic long-term memory, model-owned tool authorization (SRS §3.6, §6.4; design §2.2).

---

## 15. Decision Classification Summary

- **Confirmed (from SRS/design):** the 51 mandatory requirements; confirmed constraints (SRS §8.3); ADR-004 orchestrator-as-deterministic-state-machine; delegation depth one; RAG-not-truth; non-goals.
- **Proposed milestone organization (owner approval):** the 8-milestone structure, ordering, entry/exit criteria, and learning allocation in this document.
- **Assumptions (provisional):** A-01…A-08 (§11).
- **Recommendations (need approval):** R-01…R-06 (§12).
- **Blocking questions:** BQ-1…BQ-10 (§13).
- **Deferred:** all items in §14.

No recommendation or assumption in this document has been treated as a confirmed requirement or architectural decision.

---

## 16. Owner Approval Checklist

- [ ] I approve (or amend) the **provisional architecture baseline** (BQ-1 / A-01).
- [ ] I have answered **OQ-01…OQ-07** (BQ-2…BQ-8) and recorded them in the decision log.
- [ ] I approve the **8-milestone sequence** M0–M7 (R-01), or specify changes.
- [ ] I approve keeping a dedicated **M0 gate** and **M1 walking skeleton** (R-02/R-03), or direct otherwise.
- [ ] I approve **authoring the threat model in M0** (R-04).
- [ ] I approve **excluding optional V1 items** unless change-controlled (R-05).
- [ ] I approve **fake→live smoke** integration strategy (R-06).
- [ ] I approve the **Section 7 limit/cost baseline** as provisional test boundaries (A-02 / OQ-05), pending benchmarks.
- [ ] I accept that **OQ-08/OQ-09** must be resolved before M6/M7 respectively.
- [ ] I confirm V1 remains a **personal local prototype** (OQ-10 deferred).
- [ ] I authorize proceeding to **M0** (still no production code) upon the above.

---

## 17. Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-03 | Planning (technical lead role) | Initial draft milestone plan for owner review. No code, scaffolding, or authoritative-document changes made. |
| 0.2 | 2026-08-03 | Owner | Plan finalized; M1 authorized and implemented; M0 decision/spec work started. |
| 0.3 | 2026-08-04 | Owner + agent | **M1 Complete** (owner-reviewed, fake-backed). **M0 Complete**: decisions/specs done; OpenAI/`web_search` smoke **passed** (RSK-02 retired); only NFR-003 benchmark deferred→M2 (RSK-01 carried). **M2 is now eligible to plan.** |

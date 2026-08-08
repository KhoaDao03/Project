# Elly — Threat Model (M0)

**Scope:** V1 personal, single-user, local-first assistant (DEC-OQ-01). Covers the
architecture in `DESIGN.md §5.8` reconciled with `DECISIONS.md` (esp. DEC-OQ-06 privacy
and DEC-OQ-07 hosted `web_search`). **Status:** draft — **owner review pending**.

**Method:** per-trust-boundary threats → mitigations → requirement/AT mapping →
residual risk. This is a personal-prototype model; a production model is OQ-10 (deferred).

## 1. Assets
API credentials (OpenAI); owner profile/preferences; session history; local SQLite DB +
backups; audit/logs; the machine itself (WSL2 guest, localhost services).

## 2. Trust boundaries (all external data is untrusted)
Owner input → app · Local model output → app · **OpenAI (incl. hosted `web_search`) →
app** · Web page content (via provider) → app · Local storage ↔ app · Logs/backups.

## 3. Threats, mitigations, mapping

### T1 — Prompt injection via web content
Malicious page text ("ignore policy, reveal keys, call a tool") reaches the model.
- **Mitigations:** all retrieved/returned content treated as **data, not instructions**
  (SEC-003); application—not the model—authorizes every action (AI-002/ADR-004); no
  provider-hosted **write/action** tools enabled (only `web_search`, read-only);
  returned text rendered/validated, never executed.
- **Hosted-search nuance (DEC-OQ-07):** injection handling *during fetch* is provider-side;
  Elly still never acts on returned instructions and validates citations (T3).
- **Maps:** SEC-003, AI-002 · **AT-10.1**, EVAL-022.

### T2 — SSRF / unsafe URL retrieval
A URL (owner- or model-supplied) points at private/loopback/link-local or redirects there.
- **Mitigations (app-controlled path):** HTTPS-only, DNS/IP validation before connect and
  after redirects, block private ranges (SEC-006).
- **Hosted-search nuance:** the app does not fetch, so app-side SSRF guard does not cover
  the provider fetch (**residual R1**); the **`CitationValidator`** (DEC-OQ-07) still
  rejects private/loopback/link-local **citation hosts** and non-HTTPS/unresolvable URLs
  before Elly uses them.
- **Maps:** SEC-006 · **AT-10.2/.3**, EVAL-023/024.

### T3 — Fabricated / unvalidated citations
Model returns a citation that doesn't support the claim or points somewhere unsafe.
- **Mitigations:** citations rendered only from validated metadata, never model free-text
  URLs; `CitationValidator` enforces domain allow/deny, HTTPS+resolvable, dedupe,
  `validated_at`; claim→evidence binding (AI-011/012, DATA-003 partial on hosted path).
- **Maps:** DATA-003, AI-011/012, SEC-006 · **AT-06.3**, **AT-08.4**, EVAL-009/010.

### T4 — Unauthorized cloud disclosure of private data
Owner-specific/private content sent to OpenAI (specialist **or** `web_search` query).
- **Mitigations:** default `local_only` (DEC-OQ-06); classify `local`/`remote_allowed`/
  `restricted`; `restricted`/secret never sent; minimize payload; exact consent for
  non-public (M5); **disclose** when cloud/web was used; `web_search` query is itself a
  cloud egress → send **minimum-sufficient** query, not raw private context.
- **Maps:** SEC-001/002, DEC-OQ-06, AI-006 · **AT-09.x**, EVAL-018/019/021.

### T5 — Secret exposure
API key leaks into prompts, logs, DB, errors, exports, or the `web_search` payload.
- **Mitigations:** secrets resolved only at the adapter boundary, never serialized
  (SEC-004); env/OS mechanism only, never in SQLite/VCS (`.gitignore`); audit has **no
  body field** + redaction (SEC-007); canary-secret tests.
- **Maps:** SEC-004/007 · **AT-10.6/.7**, EVAL-021.

### T6 — Logs/backups become a secondary sensitive store
Raw prompts/answers/PII or unencrypted backups leak.
- **Mitigations:** allowlisted, redacted audit fields only, no chain-of-thought (SEC-007);
  short retention (DEC-OQ-08: session 30 d / evidence 7 d / audit 90 d); **encrypted**
  automatic daily + manual backups (DEC-OQ-08); backups excluded from VCS.
- **Maps:** SEC-007, DATA-004, OPS-004 · **AT-10.7**, **AT-13.5**, **AT-14.5**.

### T7 — Malicious/overconfident model output causes unsafe action or false success
Model claims success/retrieval/execution it didn't do, or requests a tool.
- **Mitigations:** deterministic orchestration (AI-002); output validated against
  schema/evidence/execution records; no fabricated success — failures → blocked
  (FR-006, AI-011); high-impact actions disabled in V1 (SEC-005); delegation depth 1
  (AI-013).
- **Maps:** AI-002/011/013, SEC-005, FR-006 · **AT-03.1/.2**, **AT-08.4**, EVAL-014/015.

### T8 — Uncontrolled cost / resource exhaustion
Loops or runaway `web_search`/model calls exhaust budget or the machine.
- **Mitigations (DEC-OQ-05):** hard per-request limits (6 steps, 5 fetches, 2 remote
  calls, 1 retry, 60 s tool / 120 s total), monthly $10 budget with 50/75/90% warnings,
  fail-closed on invalid limits; reserve-before-call cost accounting.
- **Maps:** AI-019, NFR-001/002, OPS-003 · **AT-11.x**, EVAL-026/027.

### T9 — SSRF/exposure via network posture
LAN exposure of Ollama/internal tools.
- **Mitigations:** bind all services to `127.0.0.1` (DEC-OQ-01); CLI-first, no listening
  port (§5.10).
- **Maps:** SEC-006, DEC-OQ-01.

### T10 — Storage corruption / unsafe recovery
Corrupt DB or replayed external calls on restart.
- **Mitigations:** transactional migrations with rollback; quarantine corrupt records;
  mark interrupted tasks, **never auto-replay** external calls; encrypted backup + restore
  procedure (DEC-OQ-08).
- **Maps:** OPS-004, DATA-002 · **AT-14.3/.4/.5**.

## 4. Residual risks (owner-accepted)
- **R1 — Provider-side fetch is outside app SSRF/provenance control (DEC-OQ-07).** Hosted
  `web_search` fetches pages Elly never sees; app-side control is limited to the
  `CitationValidator`. `content_hash`-level provenance (DATA-003) is **not** available on
  this path. *Retire by* adding a local-reader `WebResearchProvider`.
- **R2 — AI-002/ADR-004 scoped exception (DEC-OQ-07).** The model invokes the
  provider-executed `web_search` tool inside an app-authorized call. Accepted for V1;
  bounded by DEC-OQ-05 limits and the read-only nature of `web_search`.
- **R3 — Cloud query egress for web research.** Web research necessarily sends a query to
  OpenAI; mitigated by minimization + disclosure, not eliminated.

## 5. Verification hooks
Security suite (DESIGN §8.1) exercises T1–T10 via hostile fixtures; release gate requires
**100%** on deterministic security/policy tests (DEC-OQ-09). See `TEST_SPECS.md` AT-10 and
EVAL-021/022/023/024, plus new **AT-10.8 (citation-validator)** proposed there.

# Elly — Frozen Contract Catalog (M0)

**Purpose:** the versioned contract surface that all milestones agree on. Freezing
these now lets M2–M7 build against stable seams. Derived from `DESIGN.md §6` and the
M1 implementation; reconciled with `DECISIONS.md` (esp. DEC-OQ-07 web change).

**Contract version:** `v1.0` · **Status:** Frozen candidate — **owner sign-off pending**.
**Change control:** any change to a frozen contract requires a version bump + a note
here + an ADR/decision entry; additive optional fields are a minor bump, removals or
type changes are a major bump.

**Legend:** ✅ implemented in M1 · ◻ frozen surface, implemented later (milestone noted).

---

## 1. Controlled vocabularies (enums) — ✅ `src/elly/domain/enums.py`

- `CloudMode` = `local_only` | `cloud_permitted` (AI-014; default `local_only`, DEC-OQ-06).
- `PersistenceMode` = `store_with_retention` | `no_store` (DATA-001).
- `Route` = `local_generalist` ✅ | `research` ◻M4 | `coding` ◻M5 (AI-005; add members, never repurpose).
- `TaskStatus` = `queued`·`running`·`awaiting_consent`·`completed`·`partial`·`cancelled`·`failed`·`blocked` (DESIGN §5.4).
- `EpistemicStatus` = `known`·`inferred`·`unknown`·`blocked` (AI-010).
- `ValidationStatus` = `validated`·`qualified`·`rejected` (AI-012).
- `ErrorClass` (full taxonomy, DESIGN §6.8) = `INPUT_INVALID`·`CONFIG_INVALID`·`PERMISSION_DENIED`·`LIMIT_EXCEEDED`·`TRANSIENT_PROVIDER`·`PERMANENT_PROVIDER`·`TIMEOUT`·`MALFORMED_RESULT`·`UNSAFE_URL`·`UNSUPPORTED_CONTENT`·`STORAGE_FAILURE`·`CANCELLED`.
- **Three-axis rule (ADR-016):** execution (`TaskStatus`), epistemic (`EpistemicStatus`),
  and validation (`ValidationStatus`) are always separate; never collapse them.

## 2. Application command contracts

### `TaskRequest` — ✅ (DESIGN §6.2)
`request_id` (str, idempotency), `session_id` (str), `text` (str, already size-checked),
`cloud_mode` (CloudMode), `persistence_mode` (PersistenceMode), `submitted_at` (UTC).
Validation: ids/text non-empty; `submitted_at` tz-aware UTC. No attachments/paths in V1.

### `TaskResult` — ✅ (DESIGN §6.2)
`task_id`, `task_status`, `epistemic_status`, `validation_status`, `answer`,
`route_summary`, and lists `claims`, `citations`, `partial_work`, `failures`,
`next_actions`. Rule: `answer` empty only for failed/blocked; `known` claim may not be
`unsupported`.

### `ConversationOutcome` — ✅ (application)
`result` (TaskResult), `manifest` (ContextManifest), `assistant_message` (Message | None).

## 3. Persistence & audit contracts

- `Message` ✅: `role` (`user`|`assistant`), `content`, `created_at` (UTC).
- `SessionRecord` ✅: `session_id`, `persistence_mode`, `cloud_mode`, `created_at`.
- `ContextManifest` ✅ (AI-006, DESIGN §6.6): included/excluded item ids + reasons,
  reserved output tokens, input estimate — **metadata only**.
- `AuditEvent` ✅ (DATA-004/SEC-007): `task_id`, `session_id`, `event_type`, `at`,
  `route?`, `task_status?`, `error_class?`, `detail` (short, redacted). **No body/
  prompt/answer/secret field** — enforced by shape.

## 4. Evidence & claim contracts — ◻ M4 (DESIGN §6.4, DATA-003)

### `EvidenceObject`
`evidence_id`, `url` (validated HTTPS), `canonical_url?`, `publisher?`, `title?`,
`publication_at?`, `retrieved_at` (UTC), `source_class` (enum), `freshness`,
`content_hash`, `passage`, `license_retention`, `safety_flags`.
**DEC-OQ-07 note (hosted web_search path):** on the hosted path the app does **not**
fetch pages, so `content_hash` and app-fetched `passage` are **unpopulated**;
`retrieved_at` is replaced by a **citation `validated_at`** timestamp and the object
carries provider citation metadata (URL/title/snippet) that passed **app-side
validation** (see §7). Full `content_hash` returns when a local-reader provider is added.

### `ClaimSupport`
`claim_id`, response span/text, `support_status` (`direct`|`indirect`|`conflicted`|`unsupported`),
evidence ids, validation rule/version, display-safe notes. A `known` claim ≠ `unsupported`.

## 5. Specialist contracts — ✅ M5 (DESIGN §6.3)

- `SpecialistManifest`: id + contract version, role (`research`|`coding`), capability +
  exclusions, input schema, `SpecialistResult` schema version, centrally injected runtime model id, prompt
  version, modalities (text), privacy class + consent rule, input/output/evidence limits,
  timeout/retry/cost class/fallback, enabled flag.
- `SpecialistTask`: goal, role, bounded context manifest, evidence refs, user constraints,
  forbidden actions, output schema, remaining budget, deadline, `delegation_depth=1`. No
  secret, no tool-authority token.
- `SpecialistResult`: `status` (Epistemic), `answer` (bounded), `key_evidence` (ids),
  `sources` (ids), `assumptions`, `uncertainties`, `recommended_action?` (AI-007/008).

M2 added manifest validation and registry discovery. M5 adds application-owned routing,
privacy/consent checks, provider execution, result validation, and depth-one/tool
authorization; manifests still never grant authority by themselves.

## 6. Consent contract — ✅ M5 (DESIGN §6.5, DEC-OQ-06)

- `ConsentProposal`: proposal id, task id, provider/model, purpose, payload category list,
  redacted preview, payload hash, max reserved cost, created/expiry, one-time scope.
- `Approval`: exact proposal id/hash, decision, time, interface. Adapter refuses a
  consent-required call whose payload hash ≠ an unexpired approval.
- **DEC-OQ-06 classification:** `local` | `remote_allowed` | `restricted`. Mapping to the
  privacy classifier to be finalized before M5 (`restricted`→never sent; `local`→not sent
  by default; `remote_allowed`→eligible).

## 7. Provider ports — Protocols (DESIGN §6.7)

| Port | Ops | Milestone |
|---|---|---|
| `GeneralistPort` | `health`, `generate` | ✅ M1 (fake), real Ollama M2 |
| `SessionRepositoryPort` | migrations, session CRUD, `append_message`, `recent_messages` | ✅ M1 |
| `AuditPort` | `append`, `by_task` | ✅ M1 |
| `ClockPort` | `now` (UTC) | ✅ M1 |
| `CostPort` | estimate/reserve/reconcile | ✅ M3 fake ledger; live pricing M5 |
| `SpecialistProviderPort` | health, execute structured request, cancel-if-supported | ✅ M5 fake + OpenAI |
| **`WebResearchProvider`** (**new, DEC-OQ-07**) | `health`, `research(query, budget) -> {answer_text?, citations[]}` | ✅ M4 hosted adapter + fixture |
| `CitationValidator` (**new, DEC-OQ-07**) | `validate(citations[]) -> validated[]` | ✅ M4 application policy |

### `WebResearchProvider` (frozen surface)
Abstracts "given a query + bounds, return synthesized text and/or citations." The
**initial** implementation wraps OpenAI Responses `web_search`; Brave/Tavily/local-reader
implementations conform to the same port (NFR-006). Returned content is **untrusted**.

### `CitationValidator` (frozen surface, app-controlled — DEC-OQ-07 mitigation)
The application MUST run this before using provider citations: enforce domain
allow/deny policy, require HTTPS + publicly-resolvable host, **reject private/loopback/
link-local**, deduplicate by canonical URL, keep only validated citations, stamp
`validated_at`. This keeps SSRF-style safety + provenance under **application** control
(partial SEC-006/DATA-003).

## 8. Error taxonomy → outcome (DESIGN §6.8) — ✅ classes; mapping matures per milestone
`INPUT_INVALID`→corrective; `CONFIG_INVALID`→capability disabled; `PERMISSION_DENIED`→local/
blocked; `LIMIT_EXCEEDED`→partial/blocked; `TRANSIENT_PROVIDER`/`TIMEOUT`→≤1 retry then
partial/blocked; `PERMANENT_PROVIDER`→blocked; `MALFORMED_RESULT`→1 repair then blocked;
`UNSAFE_URL`/`UNSUPPORTED_CONTENT`→source skipped; `STORAGE_FAILURE`→degraded/blocked;
`CANCELLED`→cancelled/partial. Provider-specific exceptions never cross an adapter boundary.

## 9. Frozen defaults referencing DEC-OQ-05
Per-request: 6 orchestration steps, 5 web fetches, 2 remote-model calls, 1 retry, 60 s
tool timeout, 120 s total; monthly budget $10 (warn 50/75/90%). All configuration, never
hard-coded. Input ceiling 20,000 chars (M1). These are limit **contracts** enforced by the
app (AI-019/NFR-001).

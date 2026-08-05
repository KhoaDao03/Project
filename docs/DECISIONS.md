# Elly — Decision Record (Milestone M0)

**Purpose:** Authoritative record of resolved open questions (SRS §25) and owner
decisions for V1. Resolves the provisional choices in `DESIGN.md` where noted.
**Status:** OQ-01…OQ-09 **Approved by owner** 2026-08-03. OQ-10 deferred
(pre-production). **M0 closed 2026-08-04** on decisions + drafted artifacts
(`CONTRACTS.md`, `THREAT_MODEL.md`, `TEST_SPECS.md`); **OpenAI/`web_search` smoke passed
(RSK-02 retired)**; only **NFR-003 benchmark deferred→M2** (RSK-01 carried). This
record supersedes the *provisional* status of
the corresponding `DESIGN.md` ADRs listed below; it does not alter `REQUIREMENT.md`
requirement IDs or V1 scope.

**Owner:** Khoa Dao · **Recorded by:** agent, from owner's explicit decisions.

---

## Approved decisions

### DEC-OQ-01 — Single user *(Approved)*
One trusted Windows 11 user profile with WSL2. **Bind all services to `127.0.0.1`;
do not expose Ollama or internal tools to the LAN.** Supersedes ADR-001 (provisional).
*Affects:* BUS-001, DATA-001/002, SEC-001/005. *Adds:* explicit localhost-only bind
(reinforces §5.10 "no listening network port").

### DEC-OQ-02 — Interface *(Approved)*
**CLI first.** Keep an interface-independent application core; add a local web UI
only after the core workflow is reliable. Supersedes ADR-002 (provisional).
*Affects:* FR-001, UX-001, UX-002 (optional). Matches M1 as built.

### DEC-OQ-03 — Hardware / local model *(Approved)*
WSL2 + Ollama. Host: **RTX 4090 Mobile (16 GB VRAM), 32 GB system RAM, Intel Core
i9-13980HX.** **Primary `qwen3:14b`, fast fallback `qwen3:8b`.** `gemma4:12b`
multimodal benchmark **deferred** (not part of M0 now). **Do not** select 30B+ as V1
default (qwen3:30b ≈19 GB exceeds 16 GB VRAM). Model IDs remain configuration.
Supersedes ADR-007's "exact model TBD".
*WSL2 note:* the probe showed ~15 GB RAM **inside the WSL2 guest** while the host has
32 GB — WSL2 caps guest RAM by default. If the benchmark shows CPU/RAM spillover,
raise the guest allocation via `.wslconfig` (`memory=`). VRAM (16 GB) is the binding
constraint for GPU inference; `qwen3:14b` (~9.3 GB) fits with KV-cache headroom.
*NFR-003 benchmark: **deferred by owner to M2** (not required to complete M0). Local-
model fit will be validated when the real Ollama adapter lands (M2), before M2 closes.
This is the accepted residual of RSK-01 until then.* *Affects:* AI-001, API-001, NFR-003.

### DEC-OQ-04 — OpenAI model *(Approved)*
Use the **Responses API** (`store:false`, Structured Outputs). Tiering (**updated
2026-08-04**):
- **`gpt-5.6-luna`** — normal remote specialist **[DEFAULT]** (cost-sensitive);
- **`gpt-5.6-terra`** — permitted **only** for explicitly-approved difficult operations;
- **`gpt-5.6-sol`** — permitted **only** for explicitly-approved difficult operations (top tier).

All model IDs configurable. Default `gpt-5.6-luna` **aligns with** ADR-009's proposed
initial model; terra and sol are reserved for explicitly-approved difficult operations.
*Affects:* AI-004, API-002, AI-015, OPS-003. **Validated 2026-08-04** (`scripts/openai_smoke.py`):
account exposes `gpt-5.6-luna`, `gpt-5.6-terra`, `gpt-5.6-sol`; the `store:false` +
Structured Outputs (+ `web_search`) combo succeeded on **both `gpt-5.6-luna` (default,
~1.7 s) and `gpt-5.6-terra` (~3.1 s)**. **RSK-02 retired.**

### DEC-OQ-05 — Limits / cost *(Approved)*
Hard per-request ceilings: **6 orchestration steps, 5 web fetches, 2 remote-model
calls, 1 retry per failed operation, 60 s tool timeout, 120 s total request
timeout.** Configurable **monthly** API budget, initially **$10**, with warnings at
**50% / 75% / 90%**. Dollar limits stay configuration, never hard-coded.
*Reconciliation with DESIGN §7 (flag, non-blocking):* the design used per-request
$0.25 / per-day $2 ceilings; the owner's decision sets a **monthly $10** budget plus
the per-request operation limits above. Treat the monthly budget as authoritative;
per-day $2 is **absorbed** unless the owner also wants a daily ceiling. Owner's step/
fetch/call/timeout numbers **supersede** the DESIGN §7 provisional values.
*Affects:* AI-019, NFR-001/002, OPS-003.

### DEC-OQ-06 — Privacy *(Approved)*
**Local-only by default.** Classify content as **`local` / `remote_allowed` /
`restricted`**. Never send full local files, credentials, logs, private memory, or
retrieved document chunks to cloud models without an explicit policy decision.
**Display when cloud processing was used.**
*Reconciliation (flag, resolve before M5):* the DESIGN privacy classifier (ADR-008,
UC-04, §4.6) uses a 5-label scheme (`public/owner_specific/private/secret/
unclassified`). The owner's 3-tier scheme must be **mapped** onto that classifier
before consent is implemented (M5). Suggested mapping to confirm later:
`local`→treat as private/owner_specific (not sent by default); `remote_allowed`→public/
approved; `restricted`→secret (never sent). Supersedes ADR-008's default-mode wording;
does not change the fail-closed principle.
*Affects:* AI-014, SEC-001/002, AI-006/009.

### DEC-OQ-07 — Web *(Approved "for now" — deviations need owner acknowledgment)*
**Initial provider: OpenAI hosted `web_search` tool via the Responses API**, kept
behind a generic **`WebResearchProvider`** interface so Brave, Tavily, or a local
search-and-reader pipeline can replace it later. **Reverses ADR-010** (Brave-first)
and **relaxes ADR-009's "no provider-hosted tool execution"** for the web_search
tool specifically.

**⚠ Deviations from CONFIRMED requirements — owner must acknowledge (or amend the
requirements) before M4 implementation.** Provider-hosted search moves retrieval
server-side, which weakens several application-control guarantees:

| Confirmed req | Impact of hosted web_search | Preserved / mitigation |
|---|---|---|
| **AI-002 / ADR-004** (app controls tool execution; models never directly execute tools) | The model invokes and the provider executes search/fetch **inside the API call** — not application code. | App still **authorizes each web_search-enabled call per request** and decides when web research is allowed; document as a **scoped exception** for the web_search tool only. |
| **SEC-006** (URL/SSRF validation, block private IPs/redirects) | App does **not** fetch pages, so app-side SSRF/URL guards **do not apply** to the hosted path — delegated to OpenAI. | Restored when a local-reader `WebResearchProvider` is added. |
| **SEC-003** (untrusted content / prompt injection) | Injection defense **during fetch** is provider-side. | App **still** treats returned text/citations as untrusted and never acts on embedded instructions. |
| **DATA-003** (evidence provenance incl. `content_hash`, app retrieval timestamp) | App can't hash/timestamp provider-fetched pages; provenance limited to **provider citation metadata** (URL/title/snippet). | `content_hash` field is **unpopulated** on this path; record what the provider returns; flag as reduced provenance. |
| **FR-004 / AI-009** ("retrieve only selected permitted pages"; app-side ranking + privacy filter **before** cloud) | Search + synthesis occur in **one cloud call**; app-side page selection and pre-cloud privacy filtering are **bypassed**. | Minimize the query/context sent; disclose cloud use. |
| **OQ-06 / local-first** | Web research is now **inherently cloud** (query + minimized context leave the machine). | Send minimum-sufficient payload; **display** that cloud web search was used. |

**Owner-approved mitigation — app-side citation validation (partially restores
SEC-006/DATA-003).** Even though the app does not fetch pages on this path, the
application MUST validate the provider-returned citations before using/rendering
them: enforce a **domain allow/deny policy**, require **HTTPS + publicly-resolvable**
hosts, **reject private/loopback/link-local** targets, **deduplicate** by canonical
URL, **render only validated URLs**, and stamp a local **validation timestamp** +
retained citation metadata (URL/title/snippet). Full `content_hash` over app-fetched
content stays deferred to a future local-reader `WebResearchProvider`. This keeps
SSRF-style safety and provenance under **application** control at the citation
boundary (SEC-006/DATA-003 partial), and the model's returned text is still treated
as untrusted (SEC-003).

**Preserved:** `WebResearchProvider` interface (NFR-006); app authorizes/bounds calls
under DEC-OQ-05 limits; results untrusted; cloud use disclosed; minimized payload
(OQ-06); a fully app-controlled reader can later be swapped in to **fully restore
SEC-006/DATA-003**.

**Validated 2026-08-04** (`scripts/openai_smoke.py`): a single Responses call combining
`web_search` + `store:false` + Structured Outputs succeeded on **`gpt-5.6-luna` (default,
HTTP 200, ~1.7 s) and `gpt-5.6-terra` (~3.1 s)**. **Cost note (OPS-003/DEC-OQ-05):** the
`web_search` tool is token-heavy — a trivial query used ~4.5–4.6k total tokens (input
~4,477–4,559) — factor this into the $10/month budget. *Affects:* FR-003/004, API-002/003, AI-002/009, SEC-003/006, DATA-003,
OQ-06. *Status:* **Approved + feasibility-validated (hosted web_search + app-side citation
validation).** The
AI-002/ADR-004 relaxation is a documented, owner-accepted **scoped exception** for the
web_search tool; app-side validation mitigates SEC-006/DATA-003 as above.

### DEC-M4-02 — Qualified hosted summaries without claim passages *(Owner-approved, 2026-08-05)*

When hosted research returns at least one relevant, application-validated citation
but no claim-supporting source passage, Elly may display the provider's answer only
inside an explicit **Unverified provider summary** region. The result is
`inferred`, carries no verified claim bindings, and separately states that verified
facts are absent. Conflicting summaries remain `unknown`; invalid/no-source results
remain `unknown`. Instruction-shaped lines, control characters, and free-form URLs
are removed, and only application-validated citations render as links. This
provides a useful qualified response without treating citation metadata as proof.

*Related:* AI-010/011/012, UX-001, DATA-003, DEC-OQ-07.

### DEC-OQ-08 — Storage / retention / recovery *(Approved)*
Adopt DESIGN defaults: **SQLite (WAL)** with OS/disk protection; retention —
**session bodies 30 d, evidence passages 7 d, audit metadata 90 d, confirmed profile
until deletion**; no-store honored; versioned/transactional migrations; **RTO
best-effort** (personal prototype).
**Backups:** **automatic encrypted daily backups, plus manual on-demand backup →
~24 h RPO.** (Refines ADR-014, which specified encrypted owner-initiated backups, by
adding a scheduled daily job; encryption + a documented restore procedure remain
required.) Confirms ADR-006/011/013. *Affects:* DATA-001/002/004/005, SEC-007,
OPS-004. *Gates M6.*

### DEC-OQ-09 — Evaluation rubric / release thresholds *(Approved)*
Adopt DESIGN §8.4: **deterministic safety/schema/limit tests 100%; routing ≥90% with
0 unauthorized cloud/tool calls; citation support 100% in controlled fixtures;
required abstention/blocked 100%; relevant evidence in top set ≥90%; concision rubric
avg ≥4/5 with no safety-critical item <4; hardware thresholds from the NFR-003
benchmark.** *Affects:* NFR-003/004, AI-005/008/010/012. *Gates M7.*

### DEC-M7-01 — Conservative cloud reservation pricing *(Owner-provided rates, applied 2026-08-05)*

The provided remote text rates are input `$0.20/1M tokens`, cached input
`$0.02/1M tokens`, and output `$1.20/1M tokens`. The shared guardrail ledger
currently reserves a fixed amount per attempted remote call rather than billing
provider token usage directly. Configure `[pricing].remote_call_reservation_usd = 0.01` and a
`$10/month` ceiling as a conservative development reservation. This exceeds the
token-only estimate for the bounded request envelope and leaves allowance for an
unspecified tool-call fee. Local Ollama calls remain zero-cost. Once the exact
search/computer-use fee is known, this reservation must be recalibrated and the
decision amended; it must not be silently set back to zero.

---

### DEC-M7-02 — Honest claim support and prototype backup encryption *(Owner-approved, 2026-08-05)*

Research remains conservative: a validated citation URL or provider prose alone
does not establish claim support. When no selected evidence contains a direct safe
support passage, the application returns `unknown`, emits no claims, and does not
upgrade the result to `known`. A claim-support-capable provider response may be
added later without weakening this fail-closed behavior.

For the personal prototype, the owner accepts the existing basic authenticated
backup envelope in `operations.py` as sufficient to demonstrate backup/restore.
A vetted AEAD/key-management dependency is deferred to a later version and remains
a production prerequisite. This does not represent the prototype construction as
production-grade cryptography.

## Still open

- **OQ-10 — Production threat/legal/incident scope.** Deferred (pre-production only);
  not required for V1 build.

## M2 operating amendments

### DEC-M5-01 — Privacy-class mapping for cloud specialists *(Owner-approved, 2026-08-04)*

For M5, map the approved three-tier privacy policy as follows: `local` is treated as
private/owner-specific and is not sent by default; `remote_allowed` is public/approved
and may proceed in `cloud_permitted`; `restricted` is secret/highly sensitive and is
never sent to a cloud provider; `unclassified` fails closed. Local-class payloads
require one-time exact consent bound to the payload hash, provider, model, purpose,
categories, expiry, and maximum reserved cost. This resolves the DEC-OQ-06 mapping
flag without changing the local-only default.

*Related:* AI-014, SEC-001/002/004, AT-09, AT-10.5/.6.

### DEC-M2-01 — Local model profiles *(Owner-directed, 2026-08-04)*

Use **`qwen3:8b`** for development and testing by default. Use **`qwen3:14b`**
only for an explicitly selected request/configuration because other device
workloads can exhaust available VRAM. The active provider/model are configuration
values (`provider`, `model_id`, or `ELLY_GENERALIST_MODEL_ID`); the application
never silently upgrades from 8B to 14B. The opt-in example is
`config.qwen3-14b.example.toml`.

*Related:* AI-001, API-001, NFR-003, AT-02, AT-15. This amends DEC-OQ-03's
development/default selection without removing qwen3:14b from the approved V1 set.

### DEC-M2-02 — Declarative specialist registry foundation *(Owner-directed, 2026-08-04)*

Specialists are declared through validated TOML manifests and a registry rather
than hard-coded router branches. M2 implements discovery and validation only;
execution, routing, consent, provider/tool grants, and specialist result handling
remain M5 scope. Invalid manifests are disabled and never routable.

*Related:* BUS-003, AI-003/005/015, AT-03.3/.4, UC-12.

### DEC-M2-03 — qwen3:8b development performance approval *(Owner-approved, 2026-08-04)*

The owner approves the observed qwen3:8b local performance for development and
testing. The qwen3:8b live adapter smoke returned non-empty output in 2450 ms;
the detailed evidence is recorded in `docs/M2_QWEN3_8B_BENCHMARK.md`. This approval
does not authorize automatic use of qwen3:14b or replace the final M7 evaluation.

## Provisional ADRs affected by this record
- **Approved:** ADR-001, ADR-002, ADR-007 (model pinned), ADR-008 (default + labels,
  see reconciliation).
- **Approved with change:** ADR-009 — Responses API + tiering (**luna default; terra/sol escalation-only**) approved,
  **but** its "no provider-hosted tool execution" clause is **relaxed for the
  web_search tool** per DEC-OQ-07 (pending deviation acknowledgment).
- **Reversed:** ADR-010 — Brave-first replaced by hosted `web_search` behind a
  `WebResearchProvider` interface (DEC-OQ-07).
- Others remain as in `DESIGN.md`.

## Revision history
| Date | Change |
|---|---|
| 2026-08-03 | OQ-01…07 recorded as Approved; OQ-08/09 recommended defaults noted (open). |
| 2026-08-03 | Hardware corrected (RTX 4090 Mobile / 32 GB / i9-13980HX). OQ-07 changed to hosted `web_search` + `WebResearchProvider` with **app-side citation validation** (owner-approved scoped exception). OQ-08 (storage) and OQ-09 (eval thresholds) **Approved** (DESIGN defaults / §8.4). Only OQ-10 remains (deferred). |

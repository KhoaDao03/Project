# M4 — Web Research, Evidence & Epistemic Honesty

**Status:** **Reopened by independent verification 2026-08-04.** Hosted search and
citation URL validation work, but live annotations did not provide claim-level
support. Post-audit repairs add deterministic relevance/reliability ranking,
freshness rejection, deduplication, token-budget eviction, and conservative
claim abstention; choosing a claim-support-capable live contract remains an owner
decision for `known` answers. Under DEC-M4-02, validated metadata without a claim
passage now yields a clearly separated, sanitized `inferred` provider summary
instead of an empty response. The original completion
evidence below is retained as historical implementation evidence.

## Implemented

- Freshness routing for current-information and explicit research requests.
- OpenAI Responses API adapter using `store:false` and read-only hosted `web_search`.
- Deterministic fixture provider for network-free contract and security tests.
- Application-side HTTPS/public-host citation validation, private/loopback/link-local
  rejection, canonical deduplication, and evidence metadata stamping.
- Explicit `/mode cloud` gating for web queries; missing OpenAI credentials disable
  hosted research without disabling local Ollama conversation.
- Evidence states, claim bindings, numbered source rendering, conflict→`unknown`,
  and quarantine of instruction-shaped returned web text.
- Post-retrieval evidence selection ranks primary/relevant passages, excludes stale
  current-information evidence, and never overruns its deterministic token budget.
- Unsupported hosted prose is usable only in an explicit unverified region with
  zero verified claims; conflicts remain `unknown` and free-form links are omitted.
- Financial-index terminology is normalized for evidence relevance, explicit
  lookup/status language routes to research, and underspecified follow-ups carry
  one prior user subject under the same privacy/consent classification.

## Verification evidence

- Deterministic suite covers ten current-question fixtures, freshness routing, hostile
  URLs, private DNS resolution, duplicates, conflicts, injection, and CLI integration.
- Live OpenAI smoke authenticated, confirmed configured models, and the actual adapter
  returned a non-empty current answer with three citation URLs using `gpt-5.6-luna`.
- The combined `web_search + Structured Outputs` probe returned provider HTTP 500;
  isolated `web_search-only` and `structured-only` probes passed. M4 uses the approved
  web-search-only path and records this provider limitation.
- Final strict suite: **116 passed, 0 failed**.

## Approved hosted-path limitations

DEC-OQ-07 intentionally scopes M4 to OpenAI hosted search. Elly does not fetch page
bodies locally on this path, so application content hashes, page-body extraction,
redirect re-checks, content-type/byte enforcement, and full local-reader SSRF controls
are not claimed. Brave, a local page reader, and full passage RAG remain deferred.

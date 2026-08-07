# Conversation-Driven Improvement Log

**Period:** 2026-08-04 through 2026-08-06
**Scope:** Work requested and verified during the owner/Codex conversation that
began with independent release verification and continued through configuration,
hosted research, financial lookups, routing, and conversational awareness.  
**Current deterministic baseline:** **209 passed, 0 failed, 0 skipped**.

This log consolidates the thread-level work. The detailed independent findings
remain in [V1_VERIFICATION_REPORT.md](V1_VERIFICATION_REPORT.md), while
[CHANGELOG.md](CHANGELOG.md) remains the release-oriented summary.

## 1. Independent verification and owner-independent blocker repairs

The implementation was checked against the milestone plan, frozen contracts,
recorded owner decisions, acceptance specifications, and live/local boundaries.
Existing owner changes in the dirty worktree were preserved.

The following issues that did not require a new owner decision were repaired:

- Corrected the release harness so deterministic and hardware gates cannot claim
  success when they were not run.
- Hardened localhost Ollama URL validation against user-info host confusion and
  invalid origins.
- Made consent exact, one-shot, expiry-bound, and bound to payload, provider,
  model, purpose, privacy category, and maximum reserved cost.
- Redacted secret values from consent previews and durable audit details.
- Prevented hosted calls until approval metadata is durably audited.
- Rejected unsafe citation URLs, including credentials, nonstandard ports,
  direct/encoded IPs, and local/internal hosts.
- Required exact consent before owner-specific content can be included in hosted
  research or specialist payloads; restricted content remains prohibited.
- Corrected local output-limit wiring so Ollama uses the generalist ceiling rather
  than inheriting the larger specialist ceiling.
- Persisted successful research and specialist assistant turns so later
  conversation context and history remain complete.
- Fixed the specialist result-field mismatch that crashed successful completion.
- Enforced strict specialist result types, scope, output ceilings, and false
  performed-action rejection.
- Made cancellation close the active Ollama response stream and preserve partial
  work without reporting success.
- Capped each provider wait by the remaining total request timeout.
- Unified per-request step, provider-call, retry, concurrency, and cost accounting
  across local, research, and specialist workflows.
- Added independent retention, periodic maintenance, health probes, redacted
  trace details, and source/audit cleanup behavior for implemented routes.

## 2. Centralized provider, model, and pricing configuration

Operational choices now live in one main TOML file:

```toml
[providers]
generalist = "ollama"
research = "openai_web_search"
specialists = "openai"

[models]
generalist = "qwen3:8b"
research = "gpt-5.6-luna"
specialist_default = "gpt-5.6-luna"

[pricing]
monthly_budget_usd = 10
remote_call_reservation_usd = 0.01
consent_max_cost_usd = 0.25
```

- Normal startup automatically loads `config.local.toml` when present.
- Environment variables remain the final override layer.
- Specialist manifests retain capability and security policy, but do not contain
  provider model IDs or dollar pricing.
- All specialist manifests, including `stock_analysis`, inherit
  `models.specialist_default`; optional exceptions stay in the same file under
  `[models.specialists]`, for example `stock_analysis = "gpt-5.6-terra"`.
- `/status` displays resolved providers, models, reservation price, consent
  maximum, monthly budget, limits, and current usage without exposing secrets.
- Legacy configuration keys remain accepted for migration, with central values
  taking precedence.

## 3. Research behavior and evidence honesty

Hosted research is a current-information path, not a second general chat model.
It uses the configured OpenAI Responses API `web_search` tool with `store:false`,
then validates provider-returned source metadata inside Elly.

The evidence behavior was clarified and repaired:

- Valid source metadata proves that a public source was consulted; it does not by
  itself prove which sentence or numerical claim that source supports.
- Only an exact safe cited passage can create a verified claim and `known` result.
- The owner selected the current-provider policy: when source metadata is valid
  but claim-level passages are absent, retain a sanitized provider answer in an
  explicitly separated **unverified provider summary**, mark it `inferred`, keep
  verified facts/claims empty, and preserve validated source links.
- Conflicting summaries remain `unknown`.
- No-source or invalid-source results do not become verified facts.
- Instruction-shaped content, control characters, free-form URLs, and unvalidated
  Markdown links are quarantined or omitted from the unverified summary.

This directly addresses the observed state: “metadata found, but unable to
verify which claims it supports.” The response remains useful without pretending
that metadata is claim-level evidence.

## 4. Hosted-search reliability and financial lookup improvements

- Required `web_search` with `tool_choice: "required"`; merely advertising the
  tool had allowed the model to skip it.
- Requested and parsed `web_search_call.action.sources` in addition to inline
  annotations.
- Classified empty or uncited provider output as transient so the existing
  bounded guardrail can retry it once, with every attempt still cost-accounted.
- Replaced the hard-coded 512-token hosted-research limit with configurable
  `research.max_output_tokens`, now defaulting to 2,048 tokens. This leaves room for
  reasoning plus a cited final response.
- Added financial-quote instructions requiring the latest available level,
  timestamp/date, delay caveat, and market status when available; delayed quotes
  must not be represented as real-time.
- Normalized S&P 500 spellings and symbols (`S&P500`, `S&P 500`, `SP500`, `SPX`,
  and `GSPC`) plus index/indexes/indices and price/point/value variants.
- Improved evidence relevance matching for sparse source objects by considering
  validated public URL paths as well as titles and snippets.
- Recognized explicit lookup language such as “look it up,” “go look,” and
  “check online” as current-information intent.
- Added public market classifications for commodity prices, metals, crude oil,
  natural gas, exchange rates, cryptocurrency, and bond/treasury yields.
- Preserved privacy precedence: “price of gold” is public, while “my gold
  portfolio” remains local/private.
- Enforced `research.max_results` on rendered sources.
- Canonicalized and collapsed common tracking-only URL variants before evidence
  selection, eliminating large duplicate source dumps.
- Included accepted/rejected source counts in bounded research audit metadata.

The 2026-08-06 owner rerun exposed a second reliability layer: a search can run
successfully without yielding evidence suitable for a current financial quote.
The S&P request used both allowed provider attempts but returned no usable cited
source; the gold request returned 48 candidate source records, of which the old
lexical selector retained five, primarily Reddit and a news article. Their
retrieval timestamp showed when Elly received the metadata, not when the quoted
market value was published. Therefore neither a successful lookup nor a current
retrieval timestamp established that the number itself was current.

The general repair is now:

- Current market-value queries require direct quote/index paths; news, article,
  forecast, analysis, opinion, Reddit, and Quora sources are rejected for that
  purpose. Established exchanges, index administrators, and market-data hosts
  win ranking ties.
- Hosted search is anchored to the exact UTC request time and instructed to use
  direct quote feeds, report quote time/date, delay, and market status, and state
  unavailability instead of substituting an old story or forecast.
- The web-search request uses required search, medium context, explicit external
  access, and blocked community domains. Its output allowance is 2,048 tokens.
- The one allowed retry carries a targeted citation-repair instruction rather
  than sending the same failed request twice.
- Valid citations without a top-level provider summary proceed to local evidence
  validation; no-citation results remain retryable failures.
- `www`/bare-host and trailing-slash source variants canonicalize to one source.
- Text acknowledging different provider quotes or varying prices is treated as a
  conflict and remains `unknown`, never a verified fact.

Observed live outcomes during owner verification:

- S&P 500 lookup returned a sourced, explicitly `inferred` current summary rather
  than an empty abstention.
- Gold spot lookup returned a sourced, explicitly `inferred` quote with delay and
  market-status caveats.
- Source output was subsequently bounded and deduplicated.

## 5. Context-aware routing and conversational awareness

The initial follow-up repair was replaced by one general conversation-context
capability rather than accumulating topic-specific keyword patches.

- Added a bounded, role-aware resolver shared by route selection, local prompts,
  hosted research, and specialist tasks.
- Dependent wording—including pronouns, “how/what about,” “tell me more,”
  “which one,” “same for,” and continuation forms—uses the nearest relevant
  exchange and retains the original user intent across multi-step follow-ups.
- Routing considers current text plus user-authored prior intent. Prior assistant
  prose cannot create web-search authority.
- Local generalist prompts receive clearly delimited recent history, with the
  current user request taking precedence.
- Dependent hosted research and specialist calls receive only bounded relevant
  context; unrelated independent requests do not inherit prior hosted context.
- Prior assistant responses are labeled untrusted conversational context and must
  be verified before reuse.
- The complete dependent outbound context is privacy-classified before a remote
  call. A public-looking follow-up to private owner context therefore still
  requires exact consent.
- Resolved routes are recorded consistently in audit events.
- Session isolation remains intact. `no_store` mode cannot reconstruct message
  bodies after restart by design.

Examples now covered by regression tests:

- “What is the price of gold?” → “How about silver?” stays on web research and
  carries the prior price intent.
- “What is the latest Python release?” → “What about Rust?” inherits web intent.
- “Explain how gold conducts electricity.” → “What about silver?” remains local
  because the preceding intent is timeless.
- Dependent specialist requests receive the relevant prior exchange.
- Assistant text mentioning “latest” cannot independently force a web route.

## 6. CLI and operational improvements

- Updated the startup banner to the milestone-neutral “Elly local-first
  assistant.”
- Kept `Evidence`, `Route`, sources, typed failure, and next-action presentation
  explicit.
- Made `/status` expose the resolved centralized runtime and budget state.
- Preserved redacted durable audit, trace, source, retention, and backup controls.

## 7. Verification evidence

- Final strict regression suite: **209 passed, 0 failed, 0 skipped**.
- Python compilation: pass.
- `git diff --check`: pass.
- Release evidence artifact:
  `/tmp/elly-v1-market-freshness-evidence.json`.
- Frozen catalog: 30 cases; deterministic gate pass; historical hardware evidence
  pass; aggregate quality and owner UAT remain pending; `releasable=false`.
- `ruff` and `mypy` were not installed, so they were not represented as executed.

## 8. Intentional limits and remaining owner-controlled work

The work above does not silently close the remaining release gates:

- Approve the authoritative cloud pricing/reservation policy rather than treating
  the provisional configuration value as final pricing evidence.
- Complete aggregate live-quality scoring for EVAL-001 through EVAL-030.
- Complete and sign owner UC-01 through UC-12 UAT.
- Approve a vetted backup AEAD/key-management dependency and complete recovery
  acceptance if that remains in V1 scope.
- Claim-level `known` hosted answers remain unavailable when the provider supplies
  source metadata without cited passages. The selected behavior is an honest,
  useful `inferred` summary; a future provider/contract upgrade is optional if
  stronger claim grounding is desired.

No release-ready claim is made by this log.

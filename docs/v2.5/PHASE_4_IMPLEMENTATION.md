# Elly V2.5 Phase 4 — Web Research and Freshness

> Final architecture note: the temporary historical route presentation
> described below was removed before closure. See
> [LEGACY_ROUTING_REMOVAL.md](LEGACY_ROUTING_REMOVAL.md).

**Status:** Implemented
**Baseline:** Phase 3 manifest-driven specialist routing
**Scope:** Web research intent contracts, current/news/release operations, and
live-information selection

## Delivered

- Expanded the web-research descriptor into a normal catalog capability with:
  `public_information.search`, `news.current`, `release.lookup`, and
  `market.quote` operations.
- Kept `research.search` as a narrow V2 compatibility alias so historical
  route proposals and execution requests remain valid without making it the
  preferred catalog contract.
- Declared current freshness for public-information, news, and release lookup;
  declared live freshness for market quotes with bounded ticker/company/security
  metadata.
- Reused the existing generic candidate matcher: live-only operations are not
  eligible for timeless requests, static analysis specialists cannot satisfy a
  live quote, and valuation requests continue to select `stock_analysis`.
- Passed the selected web operation's freshness into `ResearchPipeline`, so
  current/live contracts enforce stale-evidence filtering even when the query
  wording itself does not contain a temporal keyword.
- Preserved the existing provider, citation validation, privacy, consent,
  guardrail, and execution boundaries.

## Expected routing

| Request | Operation | Selection |
| --- | --- | --- |
| Search public information about Apple | `public_information.search` | `web_research` |
| Latest news about Apple | `news.current` | `web_research` |
| Latest Python release | `release.lookup` | `web_research` |
| What is AAPL trading at? | `market.quote` with live freshness | `web_research` |
| What is the current S&P500 index? | `market.quote` with live freshness | `web_research` |
| Analyze Apple's valuation | `valuation.analyze` | `stock_analysis` |

Live quote operations do not claim timeless questions merely because an asset
keyword appears in a prior context. Consequential financial requests remain
outside the routing contract and are rejected as `ACTION_UNSUPPORTED` before a
local or hosted provider is dispatched.

## Compatibility and safety

The historical `Route.WEB_RESEARCH` value remains the execution/presentation
view until the Phase 5 generic route migration. The compatibility operation is
accepted only by the web handler and does not create provider or consent
authority. Operation freshness is descriptive selection metadata; cloud access,
data disclosure, provider calls, citations, spending, and actions remain under
their existing application-owned policies.

## Verification

- Web contract tests validate all declared operations and freshness values.
- Provider-free tests cover public-information, news, release, live quote,
  valuation conflict resolution, and legacy operation preparation.
- Pipeline tests verify operation-driven stale-evidence filtering.
- Existing research, API, interface, routing, specialist, and authorization
  suites remain green.

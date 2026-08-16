# Elly V2.5 Implementation and Verification Plan

**Status:** Completed and closed  
**Requirements:** [REQUIREMENTS.md](REQUIREMENTS.md)  
**Design:** [TECHNICAL_DESIGN.md](TECHNICAL_DESIGN.md)

## Phase 0 — Approval and characterization

- Obtain owner approval or explicit deferrals for V25-ROUTE-001 through 007.
- Freeze V2 routing behavior for coding, research, web research, unavailable
  capabilities, clarification, consent, and action confirmation.
- Add static characterization showing the current capability-ID literals and
  role-based composition branch.
- Decide whether the public API keeps historical route enum values as a view or
  introduces an explicitly versioned replacement.

**Exit:** approved scope, frozen compatibility decisions, and baseline tests.

## Phase 1 — Intent and catalog contracts

- Add freshness, operation, entity, routing descriptor, task intent, candidate,
  and selection proposal DTOs.
- Extend `CapabilityDescriptor` or add a dedicated routing descriptor.
- Add immutable `CapabilityRegistry.routing_catalog()`.
- Validate duplicate operations, invalid priorities, inconsistent effects, and
  unsupported entity/freshness values at startup.

**Exit:** a provider-free catalog contract suite passes.

## Phase 2 — Generic matcher and selector

- Implement capability-neutral intent interpretation.
- Implement candidate matching and lexicographic ranking.
- Add ambiguity threshold and typed clarification alternatives.
- Validate every proposal against the current catalog.
- Ensure registration order cannot affect selection.

**Exit:** synthetic capabilities route without any capability-specific central branch.

## Phase 3 — Manifest-driven specialists

- Extend specialist manifest parsing with routing operations.
- Migrate coding and research manifests.
- Add stock-analysis operations and required ticker/company entities.
- Remove role-based route selection from composition.
- Construct every enabled specialist handler generically.

**Exit:** adding or disabling a manifest changes routability without Python edits.

## Phase 4 — Web research and freshness

- Give web research a normal routing contract.
- Declare current/news/release/live-quote operations and freshness support.
- Add generic delegation or selection behavior for live information.
- Verify valuation selects stock analysis while live quotes select a current-data
  capability.

**Exit:** finance examples follow operation and freshness contracts, not IDs.

## Phase 5 — Route and persistence migration *(implemented)*

- Introduce the generic registered-capability route.
- Persist capability ID, operation, selection reason, and contract version.
- Keep historical V2 task rows readable while using generic public routes for
  all new work.
- Remove fixed route-to-capability mappings from generic routing.

**Exit:** representative V2 databases migrate and old/new tasks render correctly.

## Phase 6 — Observability, parity, and cleanup *(implemented)*

- Add safe catalog selection reason codes and redacted trace metadata.
- Exercise equivalent routing through CLI, web, desktop/mobile, and REST test adapters.
- Add static tests forbidding capability IDs in generic interpreter/router code.
- Remove the V2 interpreter, import alias, and route fallback; retain old enum
  values only for historical row decoding.
- Update README, project context, design, and verification records.

**Exit:** no central hard-coded optional capability routing remains.

## Required test matrix

### Registry and startup

- New capability registers and becomes selectable.
- Disabled capability is visible but unavailable.
- Removed capability leaves no stale match.
- Duplicate capability/operation IDs fail startup.
- Invalid routing metadata fails startup safely.

### Interpretation and matching

- Semantically equivalent wording produces the same task operation.
- Required entities are extracted or clarification is requested.
- Misleading keywords do not establish capability scope.
- Invented capability IDs and operations are rejected.
- Malformed model proposals fail closed.

### Ranking

- Exact operation beats broad analysis.
- Satisfied required fields beat incomplete candidates.
- Live freshness excludes static-only candidates.
- Specificity beats declared priority.
- Registration order has no effect.
- Semantic ties produce clarification.

### Specialist extensibility

- A temporary manifest becomes routable without source edits.
- Coding and research retain V2 behavior through contracts.
- Stock valuation selects `stock_analysis`.
- Live stock price selects a live/current-data capability.
- Financial action language remains blocked by action policy.

### Authorization and safety

- Selected restricted payload still fails cloud authorization.
- Valid cloud consent cannot bypass specialist policy.
- Selection cannot supply or forge action confirmation.
- Manifest priority cannot bypass privacy, cost, or availability.
- No routing trace stores payloads, credentials, or model rationale text.

### Migration and interfaces

- Representative schema-v4 database upgrades additively.
- Historical capability-specific routes remain readable.
- CLI/web/desktop/REST observe the same selection and reason codes.
- V2 API compatibility tests pass or an approved API-version decision exists.

## Quality gates

- Full deterministic unit, contract, integration, security, migration, and
  interface suites.
- Ruff across source and tests.
- Strict MyPy across source.
- Python compilation and `git diff --check`.
- Static forbidden-literal and import-boundary tests.
- Limited live-provider verification remains separately declared and must never
  be inferred from deterministic fakes.

## Resolved implementation decisions

1. V2.5 adds generic route categories without introducing `api/v3`.
2. Interpretation remains deterministic; model-assisted routing is deferred.
3. Typed contracts define the controlled domain, entity, operation, freshness,
   and effect vocabulary.
4. The deterministic selector owns bounded ambiguity thresholds and alternatives.
5. Specialist manifests and typed Python descriptors share one catalog contract.
6. Routing contract versions are persisted for diagnostics, not exact replay.

## Completion checklist

- [x] Seven V2.5 requirements approved or explicitly deferred.
- [x] Registry catalog implemented and immutable.
- [x] Generic task intent and selector implemented.
- [x] Central capability-ID and role mappings removed from generic routing.
- [x] Coding, research, web research, and stock analysis migrated.
- [x] New-manifest extensibility test passes.
- [x] Ambiguity, freshness, and conflict tests pass.
- [x] Authorization separation and redaction tests pass.
- [x] Schema/public compatibility decision implemented and tested.
- [x] Full deterministic regression, compilation, forbidden-literal tests, and
  whitespace checks pass.
- [x] Ruff across source and tests and strict MyPy across source pass.
- [x] Verification report completed.
- [x] Owner acceptance recorded on 2026-08-15.

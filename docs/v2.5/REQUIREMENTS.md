# Elly V2.5 Requirements — Registry-Driven Routing

**Status:** Accepted; completed and closed 2026-08-15  
**Baseline:** Elly V2, closed 2026-08-15  
**Requirements count:** Seven

## 1. Purpose

V2 executes optional capabilities through a typed registry, but automatic
conversation routing still knows the fixed identifiers `coding`, `research`,
and `web_research`. Other registered specialists, including `stock_analysis`,
cannot normally be selected from conversation without an explicitly constructed
capability intent.

V2.5 shall remove that central capability-name knowledge. Routing shall discover
eligible operations from the current validated registry, interpret the request
into capability-neutral structured intent, rank compatible candidates using
generic rules, and validate the selected capability before execution.

## 2. Scope and terminology

- **Routing catalog:** immutable, presentation-safe selection metadata derived
  from registered capability descriptors.
- **Task intent:** capability-neutral interpretation of the user's requested
  operation, domain, entities, freshness, and possible side effect.
- **Selection proposal:** an untrusted proposed capability ID and operation.
- **Intent contract:** declarative operations, inputs, entities, freshness, and
  selection metadata published by one capability.
- **Registered capability:** an optional executable handler validated and held
  by `CapabilityRegistry`.

The words **shall** and **shall not** are mandatory for V2.5 acceptance.

## 3. V25-ROUTE-001 — Registry-driven discovery

### Requirement

The routing system shall obtain the complete set of routable optional
capabilities from `CapabilityRegistry`. Adding, removing, enabling, or disabling
a valid capability shall not require editing central routing code.

### Required behavior

- The registry shall expose an immutable routing catalog.
- Enabled, valid capabilities shall be eligible for selection.
- Disabled and unavailable capabilities shall remain visible to status and
  diagnostics but shall not execute.
- Duplicate IDs and invalid routing declarations shall fail at startup with a
  typed actionable configuration error.
- Core services and policies shall not be placed in the capability registry.

### Acceptance criteria

1. A new test capability can be registered and selected without modifying the
   interpreter, router, route enum, composition root, or existing handlers.
2. Disabling the test capability produces a typed unavailable decision.
3. Removing it leaves no stale selectable route.
4. Registry order does not determine the selected capability.

## 4. V25-ROUTE-002 — No capability-specific central branches

### Requirement

Generic intent and routing components shall not contain built-in optional
capability IDs, specialist IDs, or capability-specific selection branches.

### Required behavior

- Central routing shall operate on descriptor fields and generic contracts.
- Capability identity shall be carried in `RouteDecision.capability_id`, not
  encoded as a distinct route enum member.
- Existing coding, research, and web-research capabilities shall remain
  discoverable through declarative registration, without capability-specific
  route categories.
- Removing a capability shall not cause an attribute error or silent fallback.

### Acceptance criteria

1. A static boundary test rejects known capability-ID literals in generic
   interpreter and router modules.
2. Adding a capability does not add a central conditional branch.
3. Optional execution uses one generic registered-capability route.

## 5. V25-ROUTE-003 — Declarative intent contracts

### Requirement

Every routable capability shall publish a validated immutable intent contract.

### Minimum contract

- Capability ID and safe description.
- Supported operation IDs and descriptions.
- Accepted input types.
- Required and optional entity types.
- Domain metadata.
- Freshness requirement or capability.
- Read-only or consequential-action declaration.
- Ambiguity and clarification behavior.
- Selection specificity or priority.
- Optional bounded examples and counterexamples.

Examples and keywords may provide signals, but shall not independently establish
scope or execution authority.

### Acceptance criteria

1. Invalid operations, entity declarations, freshness values, and priorities
   fail startup validation.
2. Capability contracts can be tested without providers, storage, or a model.
3. A manifest cannot declare permissions or weaken application policy.
4. Existing capabilities publish equivalent contracts without central mappings.

## 6. V25-ROUTE-004 — Structured and validated selection

### Requirement

Intent interpretation shall produce capability-neutral `TaskIntent`. Candidate
selection shall produce an untrusted `CapabilitySelectionProposal`. The
application shall validate that proposal against the live routing catalog before
creating an executable route decision.

### Task intent fields

- Requested task or operation class.
- Domain.
- Extracted entities and their source.
- Input arguments.
- Freshness requirement.
- Expected action effect.
- Confidence and ambiguity.
- Safe rationale code.

### Selection proposal fields

- Proposed capability ID.
- Proposed operation ID.
- Validated arguments and entities.
- Confidence and ambiguity.
- Safe rationale code.
- Ranked alternatives.

### Required validation

- The capability is registered and available.
- The operation is declared.
- Required inputs and entities are present.
- Freshness needs are supported.
- The generic execution route is compatible with the descriptor.
- Ambiguous or underspecified requests request clarification.
- Privacy, consent, action, provider, cost, and execution policies approve later
  at their existing authoritative boundaries.

### Acceptance criteria

1. Invented capability IDs and unsupported operations are rejected.
2. Missing required entities produce typed clarification.
3. Low-confidence or tied candidates do not execute arbitrarily.
4. Model-produced proposals cannot bypass deterministic validation.

## 7. V25-ROUTE-005 — Dynamic specialist support

### Requirement

Every enabled specialist manifest that passes validation shall automatically
produce a routable specialist capability and catalog entry. Central code shall
not map specialist roles or IDs to routes.

### Required behavior

- Specialist manifests shall declare routing operations and entity requirements.
- `role` may remain descriptive but shall not drive a central coding-versus-
  research branch.
- A specialist manifest grants no provider, consent, tool, or side-effect
  authority.
- `stock_analysis` shall become eligible for appropriate public-company,
  financial-statement, valuation, and risk-analysis requests.

### Acceptance criteria

1. Adding `security_review.toml` makes it routable without Python changes.
2. Disabling that manifest makes it unavailable without breaking startup.
3. `stock_analysis` is selected for valuation or financial-analysis requests
   when its required company or ticker entity is present.
4. Live quote requests are delegated to a capability that declares live/current
   market-data support rather than assumed to belong to stock analysis.

## 8. V25-ROUTE-006 — Deterministic conflict resolution

### Requirement

When multiple capabilities match, the application shall resolve the conflict
through documented generic ranking rules. Registration order shall not be a
selection signal.

### Required ranking order

1. Exclude unavailable or contract-incompatible candidates.
2. Prefer candidates whose required inputs are satisfied.
3. Prefer exact operations over broader operations.
4. Prefer candidates satisfying the requested freshness level.
5. Prefer the most specific compatible domain contract.
6. Apply bounded declared priority only after the preceding rules.
7. Request clarification when leading candidates remain within the configured
   ambiguity threshold.

### Acceptance criteria

1. Reversing registry order produces the same decision.
2. Exact operation matches beat generic analysis matches.
3. A live-data requirement excludes a capability that cannot provide current data.
4. Ties return clarification with safe alternatives.

## 9. V25-ROUTE-007 — Observable and safe decisions

### Requirement

Routing results and trace records shall expose enough safe metadata to explain
selection without storing prompts, private payloads, or unrestricted model
rationales.

### Required metadata

- Selected capability and operation.
- Selection rationale code.
- Candidate count.
- Safe rejected-candidate reason codes.
- Clarification state.
- Whether freshness affected selection.

### Acceptance criteria

1. CLI and all test interfaces observe equivalent structured routing decisions.
2. Traces contain no credentials, complete prompts, private payloads, or chain of thought.
3. Unavailable and rejected candidates use stable diagnostic reason codes.

## 10. Cross-cutting safety requirements

Registry-driven selection shall not become registry-driven authorization.

A routing contract shall not authorize:

- cloud transmission or provider selection;
- disclosure of sensitive information;
- external communication;
- financial transactions or personalized financial advice;
- account, deletion, file, shell, or tool actions;
- spending above configured limits; or
- model-generated permission.

Existing cloud authorization, specialist policy, action authorization, consent,
guardrails, and capability execution validation remain authoritative.

## 11. Compatibility and non-goals

V2.5 changes new-task routing metadata to the generic categories
`local_conversation` and `registered_capability`. Existing stored tasks and
historical route values shall remain readable, but they shall not be selected,
rendered, or persisted for new work.

V2.5 does not require:

- third-party plugin loading;
- autonomous capability installation;
- a production web interface;
- external financial or communication actions;
- a model to authorize selection or execution; or
- every capability to use a live or hosted model.

## 12. Completion criteria

V2.5 is ready for acceptance when all seven requirements pass and:

1. Generic routing code contains no optional capability IDs.
2. A newly registered capability is conversationally selectable without central edits.
3. Coding, research, web research, and stock analysis route through declarative contracts.
4. Ambiguity, freshness, unavailable state, and conflicting candidates fail safely.
5. Selection remains separate from privacy, consent, action, and execution authorization.
6. V2 regression, migration, interface parity, redaction, and static-analysis gates pass.

# Elly V2.5 Technical Design — Registry-Driven Routing

**Status:** Implemented design  
**Requirements:** [REQUIREMENTS.md](REQUIREMENTS.md)  
**Baseline:** Closed V2 architecture

## 1. Current limitation

V2 separates optional capability execution from conversation orchestration, but
selection is not fully extensible:

- `DeterministicIntentInterpreter` proposes fixed capability IDs.
- `RoutingPolicy` contains fixed route-to-capability mappings.
- `Route` contains capability-specific members.
- Composition assigns specialist routes using a coding-versus-research role branch.
- A specialist such as `stock_analysis` can be registered for execution while
  remaining unreachable through ordinary conversational intent.

V2.5 removes those selection-time special cases while retaining V2 policy and
execution boundaries.

## 2. Target architecture

```text
User request
    |
    v
Capability-neutral intent interpretation
    | TaskIntent
    v
Immutable routing catalog from CapabilityRegistry
    |
    v
Generic candidate matcher and ranker
    | CapabilitySelectionProposal (untrusted)
    v
Deterministic selection validator
    | clarification, rejection, or RouteDecision
    v
CapabilityExecutionWorkflow
    |
    +--> cloud authorization
    +--> specialist policy
    +--> action authorization
    +--> consent / confirmation
    +--> provider execution and durable completion
```

Discovery and selection become dynamic. Authorization and execution remain
application-owned and fail closed.

## 3. Generic route model

Capability identity shall no longer be encoded in `Route`.

Proposed route categories:

```python
class Route(str, Enum):
    LOCAL_CONVERSATION = "local_conversation"
    REGISTERED_CAPABILITY = "registered_capability"
```

The selected identity remains explicit:

```python
@dataclass(frozen=True, slots=True)
class RouteDecision:
    route: Route
    reason_code: RouteReasonCode
    capability_id: str | None = None
    operation: str = ""
    intent: TaskIntent | None = None
    selection: CapabilitySelectionView | None = None
    clarification_required: bool = False
    clarification_fields: tuple[str, ...] = ()
```

Stored V2 route values remain readable without becoming candidates for new
work. New work persists and renders the generic route plus capability ID.

## 4. Intent contracts

### 4.1 Operation contract

```python
@dataclass(frozen=True, slots=True)
class OperationIntentContract:
    operation_id: str
    description: str
    domains: tuple[str, ...]
    accepted_inputs: tuple[str, ...]
    required_entities: tuple[str, ...]
    optional_entities: tuple[str, ...] = ()
    freshness: FreshnessSupport = FreshnessSupport.STATIC
    effect: ActionCategory = ActionCategory.NONE
    specificity: int = 50
    examples: tuple[str, ...] = ()
    counterexamples: tuple[str, ...] = ()
```

Examples and counterexamples are bounded classifier hints. They are not
authorization rules or sufficient deterministic scope evidence.

### 4.2 Capability routing descriptor

```python
@dataclass(frozen=True, slots=True)
class CapabilityRoutingDescriptor:
    capability_id: str
    description: str
    operations: tuple[OperationIntentContract, ...]
    availability: CapabilityAvailability
    availability_reason: str = ""
    priority: int = 50
```

`CapabilityDescriptor` may embed this object or expose equivalent fields. The
routing catalog must contain no handler, provider, repository, consent store, or
other mutable collaborator.

## 5. Registry routing catalog

`CapabilityRegistry.routing_catalog()` returns an immutable snapshot sorted by
capability ID for determinism. Catalog construction validates:

- unique capability and operation IDs;
- bounded descriptions, examples, and priorities;
- supported entity/input/freshness vocabulary;
- consistency between declared action metadata and operation effect;
- availability state and safe reason codes; and
- absence of policy or secret-bearing objects.

Catalog sorting is only for stable output and tests. Selection must never use
catalog order as a tie-breaker.

## 6. Capability-neutral task intent

```python
@dataclass(frozen=True, slots=True)
class TaskIntent:
    requested_operation: str
    domain: str
    entities: tuple[IntentEntity, ...]
    arguments: Mapping[str, IntentScalar]
    freshness: FreshnessRequirement
    expected_effect: ActionCategory
    confidence: float
    ambiguity: IntentAmbiguity
    rationale_code: str
```

The interpreter describes the task rather than choosing a built-in capability.
It may use deterministic parsing, an optional local classifier, or both.

## 7. Interpretation strategy

### 7.1 Recommended hybrid

1. Deterministic extraction identifies explicit entities, freshness, and
   consequential-action signals.
2. A catalog-aware interpreter proposes a domain and operation from current
   catalog metadata.
3. Generic deterministic candidate matching checks declared contracts.
4. The selection validator rejects invented IDs, unsupported operations, missing
   entities, and ambiguity.

### 7.2 Optional model assistance

A local model may receive the bounded routing catalog and return a structured
proposal. The proposal is untrusted:

- IDs must exist in the current catalog.
- Operations and entity shapes must match declarations.
- Confidence cannot override deterministic ambiguity thresholds.
- The model cannot authorize cloud access, tools, cost, or side effects.
- Malformed output falls back to deterministic handling or clarification, never
  arbitrary execution.

Unit and contract tests use a deterministic interpreter and require no network.

## 8. Candidate matching and ranking

Each `(capability, operation)` pair becomes a candidate. Matching produces
structured evidence rather than a single boolean:

```python
@dataclass(frozen=True, slots=True)
class CandidateMatch:
    capability_id: str
    operation_id: str
    compatible: bool
    required_inputs_satisfied: bool
    operation_match: MatchStrength
    freshness_match: MatchStrength
    domain_specificity: int
    declared_priority: int
    rejection_codes: tuple[str, ...]
```

Ranking is lexicographic in this order:

1. compatible and available;
2. required inputs satisfied;
3. exact operation strength;
4. freshness strength;
5. domain specificity;
6. bounded declared priority.

Capability ID and registration order must not break semantic ties. If leading
candidates remain within the ambiguity threshold, the application requests
clarification and presents safe alternatives.

## 9. Specialist manifests

Specialist manifests gain routing operations. Example:

```toml
[specialist]
id = "stock_analysis"
version = "1.1"
description = "Analyzes public companies and financial securities."
enabled = true
preferred_runtime = "cloud"
risk_level = "financial_guidance"

[routing]
priority = 70

[[routing.operations]]
id = "security.analyze"
description = "Analyze a public company or financial security"
domains = ["finance"]
accepted_inputs = ["text", "ticker"]
required_entities = ["ticker_or_company"]
freshness = "preferred"
specificity = 80

[[routing.operations]]
id = "valuation.analyze"
description = "Analyze public valuation evidence"
domains = ["finance", "valuation"]
accepted_inputs = ["text", "ticker"]
required_entities = ["ticker_or_company"]
freshness = "preferred"
specificity = 90
```

`role` may remain for prompt/persona configuration but shall not select a
central route.

## 10. Web research as a normal capability

Web research publishes operations like any other capability:

```text
public_information.search
news.current
release.lookup
market.quote
```

Its contract declares current/live information support. Stock analysis can then
declare valuation, financial-statement, and risk operations without pretending
to be a live quote provider.

Expected examples:

| Request | Task intent | Expected selection |
| --- | --- | --- |
| “What is AAPL trading at?” | `market.quote`, live, ticker=AAPL | Capability declaring live market quotes, initially web research |
| “Analyze Apple's valuation” | `valuation.analyze`, ticker/company=Apple | `stock_analysis` |
| “Compare Apple’s balance-sheet risk” | `risk.analyze`, company=Apple | `stock_analysis` |
| “Should I invest my savings in Apple?” | ambiguous financial guidance | Clarification or policy-limited informational response |
| “Buy ten Apple shares” | consequential financial transaction | Blocked; no authorized execution capability |

## 11. Composition changes

Composition shall:

1. Load and validate manifests.
2. Construct handlers generically from manifests.
3. Register every valid enabled handler.
4. Validate the full registry and routing catalog.
5. Construct one catalog-aware interpreter and generic routing policy.

It shall not contain a mapping from specialist ID or role to a
capability-specific route. Missing specialists are represented through
configured or disabled descriptors, not synthetic hard-coded handlers.

## 12. Authorization boundary

Selection establishes only that a registered capability appears suitable.

```text
selected by registry contracts
    != authorized to transmit
    != authorized to call a provider
    != authorized to spend
    != authorized to perform an action
```

The existing execution workflow continues to enforce, in order:

1. Registry lookup and availability.
2. Typed input preparation.
3. Action proposal validation.
4. Privacy classification.
5. Cloud authorization and consent.
6. Specialist policy where applicable.
7. Exact action confirmation where applicable.
8. Cancellation, execution, validation, persistence, and audit.

## 13. Observability

Add safe reason codes such as:

```text
CATALOG_NO_MATCH
CATALOG_SINGLE_MATCH
CATALOG_AMBIGUOUS
REQUIRED_ENTITY_MISSING
FRESHNESS_UNSUPPORTED
OPERATION_UNSUPPORTED
CAPABILITY_UNAVAILABLE
SELECTION_PROPOSAL_REJECTED
```

Audit metadata includes selected capability/operation, candidate count,
freshness effect, and rejection codes. It excludes request bodies, private
entities, model rationale text, credentials, and provider payloads.

The public task and trace contracts expose these fields additively:
`capability_id`, `operation`, `selection_reason_code`, `candidate_count`,
`rejected_candidate_reason_codes`, `clarification_required`, and
`freshness_affected_selection`. Rejection values are bounded diagnostic codes
from validated candidate contracts; no entity values, prompt text, or model
rationale is copied into the trace. Audit details pass through a shared
single-line, bounded redaction boundary before persistence and again at the
public API boundary.

## 14. Persistence and compatibility

The schema change shall be additive. Recommended task metadata additions:

- selected capability ID;
- selected operation ID;
- generic route category;
- safe selection reason code; and
- optional catalog/contract version;
- candidate count, safe rejected-candidate codes, clarification state, and
  freshness-selection effect.

The implementation applies these additions in schema migration 6. Migration 6
does not rewrite historical route values; older rows receive bounded defaults
and remain readable directly as historical records.

Historical V2 task rows remain readable without rewriting history. New task
rendering uses only generic categories. Public API changes use additive fields
with defaults unless a new major public API version is deliberately approved.

## 15. Startup validation

Startup fails before accepting work when:

- capability or operation IDs are duplicated;
- contracts contain invalid entities, freshness, effects, or priority;
- enabled manifests lack required routing metadata;
- descriptor and handler operations disagree; or
- a consequential operation declares an action category inconsistent with the
  executable descriptor.

Intentionally disabled capabilities remain a valid unavailable state.

The closed V2 interpreter, its import alias, and historical route fallback are
removed. Catalog interpretation and generic routing contain no optional
capability identifiers or route-selection map. Historical enum values remain
only so persisted V2 rows can be decoded.

## 16. Principal risks and mitigations

| Risk | Mitigation |
| --- | --- |
| A malicious manifest tries to grant authority | Routing metadata is descriptive; application policies remain authoritative |
| Registration order changes outcomes | Stable semantic rank tuple; ties clarify |
| Generic descriptions cause over-routing | Required entities, specificity, counterexamples, ambiguity threshold |
| Model invents a capability | Catalog membership and operation validation |
| Live price goes to an analysis-only specialist | Explicit freshness compatibility |
| Migration breaks stored route rendering | Additive fields and compatibility translation |
| Catalog becomes a service locator | Immutable metadata-only catalog type |

## 17. Definition of done

The design is complete when the seven requirements trace to passing tests, all
legacy capability literals are removed from generic routing, stock analysis and
a test-added specialist are conversationally selectable, ambiguity and
freshness behave deterministically, policy cannot be bypassed, and the complete
V2 regression and quality gates remain green.

# Elly V2.5 Closure Record

**Decision date:** 2026-08-15  
**Decision:** Completed and closed  
**Decision authority:** Owner

## Accepted scope

The owner accepts the implemented V2.5 scope and marks the iteration completed.
All seven V2.5 requirements are closed:

- immutable routing catalogs derived from the live capability registry;
- capability-neutral task intent and deterministic candidate selection;
- generic manifest-driven routing for coding, research, and stock analysis;
- freshness-aware web-research and live-market operation selection;
- generic `local_conversation` and `registered_capability` route categories;
- additive persistence and safe cross-interface routing observability; and
- removal of active V1/V2 interpreters, fixed route mappings, manifest legacy
  routes, fallbacks, and compatibility presentation for new work.

Capability selection remains separate from privacy, consent, cloud, action,
provider, and execution authorization.

## Verification basis

- 368 deterministic tests passed in the final full-suite run;
- 53 focused V2.5 routing tests passed;
- Ruff passed across source and tests;
- strict MyPy passed across 93 source files;
- Python compilation and `git diff --check` passed; and
- migration, static-boundary, redaction, persistence, and interface-parity
  coverage passed.

## Accepted boundary

Limited live-provider quality verification remains separately declared and is
not claimed as passed. This does not invalidate deterministic V2.5 closure.

Historical V2 route values remain readable only for existing persisted rows.
They are not selected, rendered, or persisted for new work. External actions
and authorization remain outside routing authority.

## Final status

V2.5 is **completed and closed**. Future work belongs to the next version or
iteration unless the owner explicitly reopens V2.5.

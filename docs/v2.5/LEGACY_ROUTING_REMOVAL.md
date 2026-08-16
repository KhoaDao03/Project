# Elly V2.5 — Legacy Routing Removal

**Status:** Implemented and verified  
**Scope:** Final pre-closure routing cleanup

## Outcome

New requests now have exactly two route categories:

- `local_conversation` for the local conversational path; and
- `registered_capability` for any capability selected from the live registry.

Capability identity is carried independently in `capability_id`, with the
selected operation in `operation`. Coding, research, web research, stock
analysis, and future specialists therefore do not require route-enum additions
or central routing branches.

## Removed

- The deterministic V1/V2 capability-specific interpreter.
- The `application.intent` import alias and its intent port.
- The active legacy-route fallback and fixed capability-to-route mapping.
- Specialist-manifest `legacy_route` declarations.
- Compatibility route properties and capability-specific presentation for new
  task results, audits, CLI output, and API views.

An explicitly supplied historical route proposal now fails closed with the
safe diagnostic `LEGACY_ROUTE_UNSUPPORTED`.

## Historical data boundary

The old enum values remain solely as a decoding contract for already-persisted
V2 rows. Repository reads return the stored historical value unchanged. They
are never used to select a capability, dispatch new work, or persist a new
result. This avoids a destructive database rewrite while keeping the active
routing architecture free of historical branches.

## Verification

- V2.5 targeted routing suite: 53 passed.
- Full deterministic suite: 368 passed.
- Ruff: passed.
- Strict MyPy: passed.
- Python compilation: passed.
- Whitespace validation: passed.

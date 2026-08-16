# V3 Phase 7 — Evidence-Bounded Local Synthesis

**Status:** Implemented and verified

## Scope

Phase 7 adds the local synthesis finalization path described by V3-SYN-001 and
V3-SYN-002. The local model receives a bounded `SynthesisInput` containing the
approved request/context, source step statuses and summaries, canonical claim
and citation identifiers, warnings, uncertainties, and explicit disagreements.

The model returns only a `SynthesisDraft`. A draft contains ordered sections
that reference known result, claim, and citation identifiers plus the required
warning and disagreement identifiers. It cannot create a claim, citation,
receipt, action, or factual presentation record.

## Implementation

- `src/elly/ports/local_synthesis.py` defines immutable input, draft, section,
  claim, citation, warning, disagreement, request, and port contracts. Its
  codec rejects unknown fields, malformed JSON, invalid identifiers, duplicate
  references, and oversized drafts.
- `src/elly/application/synthesis.py` minimizes approved typed results,
  validates every reference and status, requires all approved records and
  mandatory qualifications, and renders canonical text from application-owned
  records. Unsupported model prose has no output field and therefore cannot be
  presented.
- `src/elly/adapters/fake_synthesis.py` and
  `src/elly/adapters/recorded_synthesis.py` provide deterministic offline test
  adapters. `src/elly/adapters/ollama_synthesis.py` uses only the resolved
  `synthesis` local-model role and sends no registry, provider, or execution
  callback to the model.
- `PlanExecutor` invokes the synthesis port only after source steps are
  complete/eligible, persists validated or fallback synthesis output, and
  records a bounded fallback event when the local model, parser, validator, or
  cancellation path cannot produce a safe draft.
- `synthesis_results` now stores the selected strategy, validation state,
  referenced result IDs, and retained safe presentation output using the
  existing schema-v7 table.

## Fallback and status policy

Synthesis failure never discards completed source results. A timeout,
unavailable local model, malformed draft, or adapter-local cancellation uses a
deterministic template over the source aggregation and records
`SYNTHESIS_FALLBACK`. Owner cancellation remains `CANCELLED`; its final
presentation uses the deterministic template so retained completed work remains
visible. A draft must preserve the exact derived plan status; status elevation,
missing warnings/disagreements, unknown references, citation detachment, and
record omission are rejected.

## Verification

`tests/test_v3_phase7_synthesis.py` covers:

- two specialist results composed into one ordered response;
- claim/citation attachment and explicit disagreement preservation;
- unknown references, omitted warnings, and status elevation rejection;
- local model malformed, timeout, and cancellation fallback;
- synthesis result persistence and fallback provenance; and
- local synthesis execution through the bounded plan scheduler.

The Phase 7 targeted suite and the prior Phase 4–6 regression suites pass. The
repository-wide quality gate remains the authoritative final check for the
working tree.

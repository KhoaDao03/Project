# Elly V3.5 — Response Composer Implementation

Status: implemented on top of the V3 baseline.

V3.5 adds one application-owned post-aggregation presentation stage. Validated
conversation, specialist, research, and multi-step results converge on
`ResponseCompositionService`; the planner cannot add or remove that stage.

## Runtime boundary

`src/elly/application/response_pipeline.py` builds a frozen,
size-bounded `ResponseCompositionInput` from validated result/envelope data.
`LocalResponseComposerPort` returns only a reference-bound
`ResponseCompositionDraft`. The application validates every result, claim,
citation, warning, disagreement, and exact-record reference before deterministic
assembly. V3.5 keeps the model-authored title/narrative fields empty; drafts
that populate them are rejected until a future closed, deterministically safe
framing vocabulary is defined.

`PresentationMode` is selected by application policy:

- `COMPOSED` for substantive answers, including partial, blocked, failed, and
  disputed work;
- `EXACT_WITH_COMPOSED_CONTEXT` when an application-owned receipt/record must be
  copied unchanged; and
- `DETERMINISTIC_ONLY` for consent, confirmation, and other protocol output.

Composition is reserved durably and attempted once for eligible persisted
work. A malformed, unavailable, or
timed-out composer produces a deterministic answer while preserving the
original task status, epistemic state, citations, warnings, disagreements, and
exact records. Plan events and the retained composition record capture mode,
attempt/outcome, profile/model, bounded reference identifiers, reason code,
duration, and usage fields without prompts or private reasoning. Retained
composed output is reused during plan restart;
non-retained or interrupted attempts recover through canonical deterministic
assembly without invoking the composer again.

Personality and memory fields are inert empty placeholders; they do not load,
persist, retrieve, or transmit any data.

## Configuration migration

The canonical local roles are `conversation`, `planner`, and
`response_composer`. The old `synthesis` binding and
`synthesis_max_output_tokens` limit remain readable for the migration window
and emit a deprecation warning. Configuring both spellings is rejected rather
than selected by precedence. New configuration should use:

```toml
[local_models.roles]
conversation = "qwen_default"
planner = "qwen_default"
response_composer = "qwen_default"

[local_models.role_limits]
conversation_max_output_tokens = 512
planner_max_output_tokens = 1200
response_composer_max_output_tokens = 1600
```

Persisted V3 `DIRECT`, `TEMPLATE`, and `LOCAL_SYNTHESIS` values remain safely
parseable. New production plan builders translate the legacy synthesis choice
to the common post-aggregation pipeline; a persisted legacy synthesis node is
treated as a deterministic migration shim and never invokes the old synthesis
model when the V3.5 composer is configured.

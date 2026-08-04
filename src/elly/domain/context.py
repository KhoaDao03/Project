"""Context builder (AI-006, initial) — DESIGN §5.6.

Responsibility: select the smallest sufficient recent context for a model call and
emit an auditable ContextManifest describing what was included/excluded and why.

M1 scope (PAIR work — implemented here as a simple, reviewable baseline):
- Include up to `window` most-recent messages plus the current user text (P0/P1).
- Reserve output tokens before packing.
- Exclude older messages with reason "budget".
There is NO evidence/RAG ranking here — that is P2+ and lands in M4. Secrets/
profile handling arrive in M5/M6.

OWNER REVIEW: this is the "context builder + manifest" pair item in the M1 plan.
The token estimate is a deliberately crude word-count proxy; refining the budget
policy is a good place to extend once real limits are set (OQ-05/M0).

Non-responsibilities: does not call the model, does not persist anything.
"""

from __future__ import annotations

from ..domain.models import ContextManifest, Message


def _estimate_tokens(text: str) -> int:
    """Crude, deterministic token proxy (word count). Real estimator is later scope."""
    return len(text.split())


def build_context(
    *,
    current_text: str,
    history: list[Message],
    window: int,
    reserved_output_tokens: int,
) -> tuple[str, ContextManifest]:
    """Return (prompt, manifest) for a generalist call.

    `history` is oldest-first recent messages (already limited by the repository);
    `window` caps how many we actually include here as a second guard.
    """
    included = history[-window:] if window > 0 else []
    excluded_count = max(0, len(history) - len(included))

    lines: list[str] = []
    included_ids: list[int] = []
    for idx, msg in enumerate(included):
        # Message has no persistent id at this layer; use positional index for the
        # manifest. (A real id is added when messages carry DB ids — later scope.)
        included_ids.append(idx)
        if msg.content:  # no-store history surfaces as empty; skip blank bodies
            lines.append(f"{msg.role}: {msg.content}")
    lines.append(f"user: {current_text}")
    prompt = "\n".join(lines)

    manifest = ContextManifest(
        included_message_ids=tuple(included_ids),
        excluded_reason_counts={"budget": excluded_count} if excluded_count else {},
        reserved_output_tokens=reserved_output_tokens,
        input_token_estimate=_estimate_tokens(prompt),
    )
    return prompt, manifest

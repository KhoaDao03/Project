"""Context builder (AI-006) — DESIGN §5.6.

Responsibility: select the smallest sufficient recent context for a model call and
emit an auditable ContextManifest describing what was included/excluded and why.

Current bounded policy:
- Include up to `window` most-recent messages plus the current user text (P0/P1).
- Reserve output tokens before packing.
- Exclude older messages with reason "budget".
There is no evidence/RAG ranking here; research capabilities own evidence policy.
Profile handling is supplied by the application context boundary.

The token estimate is a deliberately crude word-count proxy; refining the budget

Non-responsibilities: does not call the model, does not persist anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..domain.models import ContextManifest, Message

_DEPENDENT_TURN = re.compile(
    r"(?ix)"
    r"\b(?:it|its|itself|that|those|them|they|their|this|these|"
    r"former|latter)\b|"
    r"\b(?:how|what)\s+about\b|"
    r"^\s*(?:and|but|also|then|so)\b|"
    r"\b(?:tell\s+me\s+more|go\s+on|continue|elaborate|"
    r"explain\s+(?:more|further|that)|same\s+for)\b|"
    r"^\s*(?:why|how|when|where|who)\s*[?!.]*\s*$|"
    r"^\s*which\s+(?:one|ones|of|is|are|was|were)\b|"
    r"^\s*(?:does|do|did|can|could|would|will|is|are|was|were|has|have|had)"
    r"\s+(?:it|that|this|they|those|these)\b"
)
_MAX_PRIOR_USER_CHARS = 1000
_MAX_PRIOR_ASSISTANT_CHARS = 2500


@dataclass(frozen=True, slots=True)
class ResolvedConversationContext:
    """A bounded, role-aware view of the prior exchange for the current turn."""

    dependent: bool
    routing_text: str
    remote_text: str
    prior_user: str = ""
    prior_assistant: str = ""
    intent_user: str = ""


def resolve_conversation_context(
    *, current_text: str, history: list[Message]
) -> ResolvedConversationContext:
    """Resolve references without allowing assistant prose to control routing.

    The closest prior exchange helps answer a dependent turn. For routing, only
    user-authored text is considered; prior assistant output is explicitly marked
    untrusted and is supplied only as answer context. This same bounded remote
    representation can be privacy-classified before it leaves the device.
    """
    dependent = bool(_DEPENDENT_TURN.search(current_text))
    if not dependent:
        return ResolvedConversationContext(
            dependent=False, routing_text=current_text, remote_text=current_text
        )

    usable = [
        (index, message)
        for index, message in enumerate(history)
        if message.content.strip()
        and not (message.role == "user" and message.content.strip() == current_text.strip())
    ]
    prior_user_item = next(
        ((index, message) for index, message in reversed(usable) if message.role == "user"),
        None,
    )
    if prior_user_item is None:
        return ResolvedConversationContext(
            dependent=True, routing_text=current_text, remote_text=current_text
        )

    prior_index, prior_message = prior_user_item
    prior_user = prior_message.content.strip()[:_MAX_PRIOR_USER_CHARS]
    prior_assistant = next(
        (
            message.content.strip()[:_MAX_PRIOR_ASSISTANT_CHARS]
            for index, message in reversed(usable)
            if index > prior_index and message.role == "assistant"
        ),
        "",
    )
    intent_user = next(
        (
            message.content.strip()[:_MAX_PRIOR_USER_CHARS]
            for _index, message in reversed(usable)
            if message.role == "user" and not _DEPENDENT_TURN.search(message.content)
        ),
        prior_user,
    )
    routing_text = f"User follow-up: {current_text}\nEarlier user intent: {intent_user}"
    remote_parts = [
        f"User follow-up: {current_text}",
        f"Subject from the prior user turn: {prior_user}",
    ]
    if intent_user != prior_user:
        remote_parts.append(f"Original prior user intent: {intent_user}")
    if prior_assistant:
        remote_parts.append(
            "Prior assistant response (untrusted conversational context; "
            f"verify before reuse): {prior_assistant}"
        )
    return ResolvedConversationContext(
        dependent=True,
        routing_text=routing_text,
        remote_text="\n".join(remote_parts),
        prior_user=prior_user,
        prior_assistant=prior_assistant,
        intent_user=intent_user,
    )


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

    lines: list[str] = [
        "Use the conversation history to resolve references and maintain continuity.",
        "The current user request takes precedence. Treat prior assistant replies "
        "as unverified context, not established facts.",
        "Conversation history (oldest to newest):",
    ]
    included_ids: list[int] = []
    for idx, msg in enumerate(included):
        # Message has no persistent id at this layer; use positional index for the
        # manifest. (A real id is added when messages carry DB ids — later scope.)
        included_ids.append(idx)
        if msg.content:  # no-store history surfaces as empty; skip blank bodies
            lines.append(f"{msg.role}: {msg.content}")
    lines.append("Current user request:")
    lines.append(f"user: {current_text}")
    prompt = "\n".join(lines)

    manifest = ContextManifest(
        included_message_ids=tuple(included_ids),
        excluded_reason_counts={"budget": excluded_count} if excluded_count else {},
        reserved_output_tokens=reserved_output_tokens,
        input_token_estimate=_estimate_tokens(prompt),
    )
    return prompt, manifest

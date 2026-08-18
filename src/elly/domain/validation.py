"""Response validation (AI-011/AI-012) — DESIGN §5.7, §4.7.

Responsibility: inspect untrusted model output BEFORE it becomes a user answer and
assign a ValidationStatus, so the system never presents fabricated success.

The local generalist contract checks that output is non-empty and usable;
capability-specific workflows perform stronger evidence/action validation before
their results become user-visible.

Returns a ValidationStatus; raising is reserved for the adapter boundary
(MalformedResultError) — here we classify.
"""

from __future__ import annotations

from .enums import ValidationStatus


def validate_generalist_text(text: str) -> ValidationStatus:
    """Classify a generalist answer.

    - non-empty, usable text -> VALIDATED
    - empty/whitespace       -> REJECTED (caller maps to blocked/failed)
    """
    if text and text.strip():
        return ValidationStatus.VALIDATED
    return ValidationStatus.REJECTED

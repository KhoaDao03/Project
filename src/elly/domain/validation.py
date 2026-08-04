"""Response validation (AI-011/AI-012, initial) — DESIGN §5.7, §4.7.

Responsibility: inspect untrusted model output BEFORE it becomes a user answer and
assign a ValidationStatus, so the system never presents fabricated success.

M1 scope (minimal): the fake generalist cannot retrieve or act, so there are no
citations/actions to verify yet. M1 checks only that the output is non-empty and
usable; empty/malformed output is REJECTED (never shown as a confident answer).
Claim-to-evidence binding and citation checks are M4 (AI-011/012 full).

Returns a ValidationStatus; raising is reserved for the adapter boundary
(MalformedResultError) — here we classify.
"""

from __future__ import annotations

from .enums import ValidationStatus


def validate_generalist_text(text: str) -> ValidationStatus:
    """Classify a generalist answer for M1.

    - non-empty, usable text -> VALIDATED
    - empty/whitespace       -> REJECTED (caller maps to blocked/failed)
    """
    if text and text.strip():
        return ValidationStatus.VALIDATED
    return ValidationStatus.REJECTED

"""Input validation at the untrusted boundary (FR-001, SEC-006 input side).

Rejects empty/whitespace and oversized input BEFORE any orchestration or model
call, and normalizes Unicode. Raising InputInvalidError here guarantees AT-01.2/.3
(no model call on bad input).
"""

from __future__ import annotations

import unicodedata

from ..domain.errors import InputInvalidError


def normalize_and_validate(text: str, *, max_chars: int) -> str:
    """Return NFC-normalized text, or raise InputInvalidError.

    - empty/whitespace-only -> InputInvalidError
    - length (after normalization) > max_chars -> InputInvalidError naming the limit
    """
    if text is None or not isinstance(text, str):
        raise InputInvalidError("input must be text")
    normalized = unicodedata.normalize("NFC", text).strip()
    if not normalized:
        raise InputInvalidError("input is empty")
    if len(normalized) > max_chars:
        raise InputInvalidError(f"input exceeds the {max_chars}-character limit")
    return normalized

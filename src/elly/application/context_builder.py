"""Application-facing context construction boundary."""

from __future__ import annotations

from ..domain.context import build_context
from ..domain.models import ContextManifest, Message


class ContextBuilder:
    """Builds bounded model context without persistence or provider access."""

    def __init__(self, *, context_window: int, reserved_output_tokens: int) -> None:
        self._context_window = context_window
        self._reserved_output_tokens = reserved_output_tokens

    def build(self, *, current_text: str, history: list[Message]) -> tuple[str, ContextManifest]:
        return build_context(
            current_text=current_text,
            history=history,
            window=self._context_window,
            reserved_output_tokens=self._reserved_output_tokens,
        )

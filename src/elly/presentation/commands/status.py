"""Application status command handler."""

from __future__ import annotations

from ...presentation import render
from .base import CommandContext, CommandResult, api_failure


class StatusHandler:
    def handle(self, args: tuple[str, ...], context: CommandContext) -> CommandResult:
        result = context.api.get_status()
        if not result.is_success:
            return api_failure(result, prefix="Status unavailable: ")
        assert result.value is not None
        active_mode = (
            f"{context.session.cloud_mode.value} / {context.session.persistence_mode.value}"
            if context.session is not None
            else None
        )
        return CommandResult(render.render_status(result.value, active_mode=active_mode))

"""CLI lifecycle command handlers."""

from __future__ import annotations

from .base import CommandContext, CommandResult

EXIT = "__EXIT__"


class ExitHandler:
    def handle(self, args: tuple[str, ...], context: CommandContext) -> CommandResult:
        return CommandResult(EXIT, exit_requested=True)

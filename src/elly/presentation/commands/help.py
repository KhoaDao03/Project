"""Generated help command."""

from __future__ import annotations

from .base import CommandContext, CommandResult
from .registry import CommandRegistry


class HelpHandler:
    def __init__(self, registry: CommandRegistry) -> None:
        self._registry = registry

    def handle(self, args: tuple[str, ...], context: CommandContext) -> CommandResult:
        if args:
            return CommandResult("Usage: /help")
        return CommandResult(self._registry.help_text())

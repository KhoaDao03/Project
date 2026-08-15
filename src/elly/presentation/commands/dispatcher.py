"""Tokenization and common command dispatch behavior."""

from __future__ import annotations

import shlex

from .base import CommandArgumentError, CommandContext, CommandResult
from .registry import CommandRegistry


class CommandDispatcher:
    """Resolve and invoke registered handlers without command-specific branches."""

    def __init__(self, registry: CommandRegistry) -> None:
        self.registry = registry

    def dispatch(self, raw: str, context: CommandContext) -> CommandResult:
        try:
            parts = tuple(shlex.split(raw))
        except ValueError:
            return CommandResult("Invalid command syntax. Check quoting and try again.")
        if not parts:
            return CommandResult("(empty input ignored)")
        descriptor = self.registry.resolve(parts[0])
        if descriptor is None:
            return CommandResult(f"Unknown command: {parts[0]} (try /help)")
        try:
            args = descriptor.parse_args(parts[1:])
        except CommandArgumentError as exc:
            return CommandResult(
                f"Invalid arguments for {descriptor.name}: {exc}. Usage: {descriptor.usage}"
            )
        try:
            return descriptor.handler.handle(args, context)
        except CommandArgumentError as exc:
            return CommandResult(
                f"Invalid arguments for {descriptor.name}: {exc}. Usage: {descriptor.usage}"
            )
        except Exception:
            # Handlers normally translate ApiResult failures themselves. Keep
            # an unexpected presentation failure safe and uniform at the edge.
            return CommandResult("Command failed: internal application error.")

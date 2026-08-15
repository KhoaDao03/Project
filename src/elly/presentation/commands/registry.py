"""Validated command registry for the terminal interface."""

from __future__ import annotations

from collections.abc import Iterable

from .base import CommandDescriptor


class CommandRegistry:
    """Own command lookup and startup validation, independent of the input loop."""

    def __init__(self, descriptors: Iterable[CommandDescriptor] = ()) -> None:
        self._descriptors: list[CommandDescriptor] = []
        self._lookup: dict[str, CommandDescriptor] = {}
        for descriptor in descriptors:
            self.register(descriptor)

    def register(self, descriptor: CommandDescriptor) -> None:
        descriptor.validate()
        names = (descriptor.name, *descriptor.aliases)
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate command name or alias: {descriptor.name}")
        for name in names:
            if name in self._lookup:
                raise ValueError(f"duplicate command name or alias: {name}")
        self._descriptors.append(descriptor)
        for name in names:
            self._lookup[name] = descriptor

    def resolve(self, name: str) -> CommandDescriptor | None:
        return self._lookup.get(name)

    def descriptors(self) -> tuple[CommandDescriptor, ...]:
        return tuple(self._descriptors)

    def help_text(self) -> str:
        lines = ["Commands:"]
        for descriptor in self._descriptors:
            lines.append(f"  {descriptor.usage:<24} {descriptor.help_text}")
        return "\n".join(lines)

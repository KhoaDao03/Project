"""Default command descriptors for the terminal presentation."""

from __future__ import annotations

from .backup import BackupHandler, RestoreHandler, validate_backup
from .base import CommandDescriptor
from .consent import ActionDecisionHandler, ConsentDecisionHandler
from .dispatcher import CommandDispatcher
from .help import HelpHandler
from .history import HistoryHandler, validate_history
from .lifecycle import ExitHandler
from .profile import ProfileHandler
from .registry import CommandRegistry
from .session import ModeHandler, NewSessionHandler, validate_mode, validate_new
from .status import StatusHandler
from .tasks import (
    CancelHandler,
    PlanHandler,
    PlanTraceHandler,
    SourcesHandler,
    TraceHandler,
    no_args,
    one_id,
)


def build_command_registry() -> CommandRegistry:
    """Create and validate the complete built-in command set."""
    registry = CommandRegistry()
    registry.register(
        CommandDescriptor(
            name="/help",
            usage="/help",
            help_text="show this help",
            handler=HelpHandler(registry),
            validate_args=no_args,
        )
    )
    registry.register(
        CommandDescriptor(
            name="/new",
            usage="/new [--no-store]",
            help_text="start a new session",
            handler=NewSessionHandler(),
            validate_args=validate_new,
        )
    )
    registry.register(
        CommandDescriptor(
            name="/mode",
            usage="/mode local | /mode cloud",
            help_text="change the session cloud mode",
            handler=ModeHandler(),
            validate_args=validate_mode,
        )
    )
    registry.register(
        CommandDescriptor(
            name="/approve",
            usage="/approve <id>",
            help_text="approve one exact cloud-consent proposal",
            handler=ConsentDecisionHandler(approve=True),
            validate_args=one_id,
        )
    )
    registry.register(
        CommandDescriptor(
            name="/deny",
            usage="/deny <id>",
            help_text="deny one cloud-consent proposal",
            handler=ConsentDecisionHandler(approve=False),
            validate_args=one_id,
        )
    )
    registry.register(
        CommandDescriptor(
            name="/approve-action",
            usage="/approve-action <id>",
            help_text="approve one exact action confirmation",
            handler=ActionDecisionHandler(approve=True),
            validate_args=one_id,
        )
    )
    registry.register(
        CommandDescriptor(
            name="/deny-action",
            usage="/deny-action <id>",
            help_text="deny one exact action confirmation",
            handler=ActionDecisionHandler(approve=False),
            validate_args=one_id,
        )
    )
    registry.register(
        CommandDescriptor(
            name="/profile",
            usage="/profile list|add|correct|delete ...",
            help_text="view or change confirmed profile items",
            handler=ProfileHandler(),
        )
    )
    registry.register(
        CommandDescriptor(
            name="/history",
            usage="/history list|delete <session-id>",
            help_text="list or delete sessions",
            handler=HistoryHandler(),
            validate_args=validate_history,
        )
    )
    registry.register(
        CommandDescriptor(
            name="/trace",
            usage="/trace <task-id>",
            help_text="show redacted durable task events",
            handler=TraceHandler(),
            validate_args=one_id,
        )
    )
    registry.register(
        CommandDescriptor(
            name="/plan",
            usage="/plan <plan-id>",
            help_text="show a safe execution-plan summary",
            handler=PlanHandler(),
            validate_args=one_id,
        )
    )
    registry.register(
        CommandDescriptor(
            name="/plan-trace",
            usage="/plan-trace <plan-id>",
            help_text="show redacted execution-plan provenance",
            handler=PlanTraceHandler(),
            validate_args=one_id,
        )
    )
    registry.register(
        CommandDescriptor(
            name="/sources",
            usage="/sources <task-id>",
            help_text="show stored source metadata",
            handler=SourcesHandler(),
            validate_args=one_id,
        )
    )
    registry.register(
        CommandDescriptor(
            name="/backup",
            usage="/backup <path>",
            help_text="create an encrypted backup",
            handler=BackupHandler(),
            validate_args=validate_backup,
        )
    )
    registry.register(
        CommandDescriptor(
            name="/restore",
            usage="/restore <path>",
            help_text="restore an encrypted backup",
            handler=RestoreHandler(),
            validate_args=validate_backup,
        )
    )
    registry.register(
        CommandDescriptor(
            name="/status",
            usage="/status",
            help_text="show dependency health and active mode",
            handler=StatusHandler(),
            validate_args=no_args,
        )
    )
    registry.register(
        CommandDescriptor(
            name="/cancel",
            usage="/cancel",
            help_text="request cancellation of the active generation",
            handler=CancelHandler(),
            validate_args=no_args,
        )
    )
    registry.register(
        CommandDescriptor(
            name="/exit",
            usage="/exit",
            help_text="quit",
            handler=ExitHandler(),
            validate_args=no_args,
        )
    )
    return registry


__all__ = [
    "CommandDescriptor",
    "CommandDispatcher",
    "CommandRegistry",
    "build_command_registry",
]

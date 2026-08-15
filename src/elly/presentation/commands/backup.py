"""Encrypted backup and restore command handlers."""

from __future__ import annotations

from ...api.contracts import BackupRequest, RestoreRequest
from .base import CommandArgumentError, CommandContext, CommandResult, api_failure


def validate_backup(args: tuple[str, ...]) -> tuple[str, ...]:
    if len(args) != 1 or not args[0].strip():
        raise CommandArgumentError("expected one backup path")
    return args


class BackupHandler:
    def handle(self, args: tuple[str, ...], context: CommandContext) -> CommandResult:
        result = context.api.create_backup(BackupRequest(args[0]))
        if not result.is_success:
            return api_failure(result, prefix="Backup failed: ")
        assert result.value is not None
        return CommandResult(f"Backup created: {result.value.path}")


class RestoreHandler:
    def handle(self, args: tuple[str, ...], context: CommandContext) -> CommandResult:
        result = context.api.restore_backup(RestoreRequest(args[0]))
        if not result.is_success:
            return api_failure(result, prefix="Restore failed: ")
        return CommandResult(
            "Backup restored after integrity validation; restart Elly before using the restored database."
        )

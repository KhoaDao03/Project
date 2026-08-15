"""Session history command handlers."""

from __future__ import annotations

from ...api.contracts import HistoryQuery
from .base import CommandArgumentError, CommandContext, CommandResult, api_failure


def validate_history(args: tuple[str, ...]) -> tuple[str, ...]:
    if args == ("list",) or (len(args) == 2 and args[0] == "delete"):
        return args
    raise CommandArgumentError("expected list or delete session-id")


class HistoryHandler:
    def handle(self, args: tuple[str, ...], context: CommandContext) -> CommandResult:
        if args == ("list",):
            history_result = context.api.list_history(HistoryQuery())
            if not history_result.is_success:
                return api_failure(history_result, prefix="History unavailable: ")
            assert history_result.value is not None
            return CommandResult(
                "\n".join(
                    f"{session.session_id} {session.created_at.isoformat()} "
                    f"{session.persistence_mode.value}"
                    for session in history_result.value.sessions
                )
                or "No sessions."
            )

        delete_result = context.api.delete_session(args[1])
        if not delete_result.is_success:
            if (
                delete_result.failure is not None
                and delete_result.failure.code.value == "NOT_FOUND"
            ):
                return CommandResult("Session not found.")
            return api_failure(delete_result, prefix="History update failed: ")
        return CommandResult("Session deleted.")

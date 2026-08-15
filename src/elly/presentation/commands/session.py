"""Session lifecycle command handlers."""

from __future__ import annotations

from ...api.contracts import ChangeModeRequest, CreateSessionRequest
from ...domain.enums import CloudMode, PersistenceMode
from .base import (
    CommandArgumentError,
    CommandContext,
    CommandResult,
    api_failure,
)


def validate_new(args: tuple[str, ...]) -> tuple[str, ...]:
    if args not in ((), ("--no-store",)):
        raise CommandArgumentError("expected no arguments or --no-store")
    return args


def validate_mode(args: tuple[str, ...]) -> tuple[str, ...]:
    if len(args) != 1 or args[0] not in {"local", "cloud"}:
        raise CommandArgumentError("expected local or cloud")
    return args


class NewSessionHandler:
    def handle(self, args: tuple[str, ...], context: CommandContext) -> CommandResult:
        persistence = (
            PersistenceMode.NO_STORE
            if args == ("--no-store",)
            else PersistenceMode.STORE_WITH_RETENTION
        )
        result = context.api.create_session(
            CreateSessionRequest(persistence_mode=persistence)
        )
        if not result.is_success:
            return api_failure(result, prefix="Session creation failed: ")
        assert result.value is not None
        return CommandResult(
            f"Started {result.value.session_id} ({persistence.value}).",
            session=result.value,
            pending_consent=None,
            pending_action=None,
            last_task_id=None,
        )


class ModeHandler:
    def handle(self, args: tuple[str, ...], context: CommandContext) -> CommandResult:
        if context.session is None:
            return CommandResult("No active session.")
        cloud_mode = (
            CloudMode.LOCAL_ONLY if args[0] == "local" else CloudMode.CLOUD_PERMITTED
        )
        result = context.api.change_session_mode(
            ChangeModeRequest(
                session_id=context.session.session_id,
                expected_version=context.session.version,
                cloud_mode=cloud_mode,
            )
        )
        if not result.is_success:
            return api_failure(result, prefix="Mode change failed: ")
        assert result.value is not None
        if cloud_mode is CloudMode.LOCAL_ONLY:
            return CommandResult("Mode: local_only.", session=result.value)
        return CommandResult(
            "Mode: cloud_permitted (hosted web research requires OPENAI_API_KEY).",
            session=result.value,
        )

"""Shared contracts for modular CLI command dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol, TypeVar

from ...api.contracts import (
    ActionDecisionRequest,
    ApiResult,
    ApplicationStatusView,
    BackupRequest,
    BackupView,
    ChangeModeRequest,
    ConsentDecisionRequest,
    ConsentQuery,
    ConsentView,
    CreateSessionRequest,
    HistoryQuery,
    HistoryView,
    ProfileCommand,
    ProfileQuery,
    SessionView,
    SourcesQuery,
    SourcesView,
    TaskView,
    TraceQuery,
    TraceView,
)


class PublicApplication(Protocol):
    """The application surface a presentation handler is allowed to use."""

    def create_session(self, request: CreateSessionRequest | None = None) -> ApiResult[SessionView]: ...

    def change_session_mode(self, request: ChangeModeRequest) -> ApiResult[SessionView]: ...

    def submit_and_wait(self, request: Any) -> ApiResult[TaskView]: ...

    def cancel_task(self, task_id: str) -> ApiResult[TaskView]: ...

    def get_profile(self, request: ProfileQuery | None = None) -> ApiResult[tuple[Any, ...]]: ...

    def change_profile(self, request: ProfileCommand) -> ApiResult[Any]: ...

    def list_history(self, request: HistoryQuery | None = None) -> ApiResult[HistoryView]: ...

    def delete_session(self, session_id: str) -> ApiResult[bool]: ...

    def get_trace(self, request: TraceQuery) -> ApiResult[TraceView]: ...

    def get_sources(self, request: SourcesQuery) -> ApiResult[SourcesView]: ...

    def list_consents(self, request: ConsentQuery | None = None) -> ApiResult[tuple[ConsentView, ...]]: ...

    def decide_consent(self, request: ConsentDecisionRequest) -> ApiResult[TaskView]: ...

    def decide_action(self, request: ActionDecisionRequest) -> ApiResult[TaskView]: ...

    def create_backup(self, request: BackupRequest) -> ApiResult[BackupView]: ...

    def restore_backup(self, request: Any) -> ApiResult[BackupView]: ...

    def get_status(self) -> ApiResult[ApplicationStatusView]: ...

    def close(self) -> None: ...


@dataclass
class CommandContext:
    """Mutable presentation state shared by one dispatch operation."""

    api: PublicApplication
    session: SessionView | None
    pending_consent: ConsentView | None = None
    pending_action: Any = None
    last_task_id: str | None = None
    help_text: Callable[[], str] | None = None


class CommandHandler(Protocol):
    """One registered command's presentation-only behavior."""

    def handle(self, args: tuple[str, ...], context: CommandContext) -> "CommandResult": ...


class CommandArgumentError(ValueError):
    """An argument list failed a descriptor's common validation."""


_UNSET = object()
T = TypeVar("T")


@dataclass(frozen=True)
class CommandResult:
    """Rendered command output plus optional presentation-state updates."""

    text: str
    session: SessionView | None | object = _UNSET
    pending_consent: ConsentView | None | object = _UNSET
    pending_action: Any = _UNSET
    last_task_id: str | None | object = _UNSET
    exit_requested: bool = False


ArgumentValidator = Callable[[tuple[str, ...]], tuple[str, ...]]


@dataclass(frozen=True)
class CommandDescriptor:
    """Stable metadata and behavior for one CLI command."""

    name: str
    usage: str
    help_text: str
    handler: CommandHandler
    aliases: tuple[str, ...] = ()
    validate_args: ArgumentValidator | None = None

    def validate(self) -> None:
        if not self.name.startswith("/") or self.name == "/":
            raise ValueError("command name must start with '/' and contain a name")
        if any(not alias.startswith("/") or alias == "/" for alias in self.aliases):
            raise ValueError("command aliases must start with '/' and contain a name")
        if not self.usage.strip():
            raise ValueError(f"command {self.name} has empty usage")
        if not self.help_text.strip():
            raise ValueError(f"command {self.name} has empty help text")
        if not callable(getattr(self.handler, "handle", None)):
            raise ValueError(f"command {self.name} has no handler")

    def parse_args(self, args: tuple[str, ...]) -> tuple[str, ...]:
        if self.validate_args is None:
            return args
        return self.validate_args(args)


def api_failure(result: ApiResult[Any], *, prefix: str = "") -> CommandResult:
    """Turn a typed public failure into safe, consistent command output."""
    assert result.failure is not None
    message = result.failure.safe_message
    return CommandResult(f"{prefix}{message}" if prefix else message)


def value_or_failure(result: ApiResult[T], *, prefix: str = "") -> T | CommandResult:
    """Return a successful public value or a renderable command failure."""
    if result.is_success:
        assert result.value is not None
        return result.value
    return api_failure(result, prefix=prefix)

"""Terminal presentation adapter backed exclusively by the public API."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import cast

from ..api.application import EllyApplication
from ..api.contracts import (
    ActionConfirmationView,
    ApiFailureCode,
    ConsentView,
    SessionView,
    SubmitRequest,
)
from ..domain.enums import TaskStatus
from . import render
from .commands import CommandDispatcher, CommandRegistry, build_command_registry
from .commands.base import _UNSET, CommandContext, CommandResult, PublicApplication
from .commands.lifecycle import EXIT


@dataclass
class Cli:
    """Thin REPL adapter: parse, dispatch, submit, render, and cache public views."""

    api: PublicApplication
    session: SessionView | None = None
    pending_consent: tuple[SessionView, ConsentView] | None = None
    pending_action: ActionConfirmationView | None = None
    last_task_id: str | None = None
    _legacy_app: object | None = field(default=None, repr=False)
    _owns_api: bool = field(default=False, repr=False)
    registry: CommandRegistry = field(init=False, repr=False)
    dispatcher: CommandDispatcher = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.registry = build_command_registry()
        self.dispatcher = CommandDispatcher(self.registry)

    @classmethod
    def start(cls, app: object) -> "Cli":
        """Start from a public façade; wrap the old composition object temporarily for compatibility."""
        if isinstance(app, EllyApplication) or callable(getattr(app, "create_session", None)):
            api = cast(PublicApplication, app)
            legacy_app = None
            owns_api = False
        else:
            # This compatibility path lets older embedders pass the composition
            # object while all command behavior still goes through the façade.
            api = EllyApplication(app)  # type: ignore[arg-type]
            legacy_app = app
            owns_api = True
        created = api.create_session()
        if not created.is_success:
            assert created.failure is not None
            raise RuntimeError(created.failure.safe_message)
        assert created.value is not None
        return cls(
            api=api,
            session=created.value,
            _legacy_app=legacy_app,
            _owns_api=owns_api,
        )

    @property
    def app(self) -> object:
        """Compatibility view for callers that still own the old composition object.

        Handlers never use this property. New entry points receive the public
        ``EllyApplication`` directly, so ``app`` resolves to that façade.
        """
        return self._legacy_app if self._legacy_app is not None else self.api

    def close(self) -> None:
        """Close a façade created by the compatibility start path."""
        if self._owns_api and hasattr(self.api, "close"):
            self.api.close()

    # -- single-line dispatch (unit-testable) ------------------------------

    def dispatch(self, line: str) -> str:
        raw = line.strip()
        if not raw:
            return "(empty input ignored)"
        if raw.startswith("/"):
            result = self.dispatcher.dispatch(raw, self._context())
        else:
            result = self._submit(raw)
        return self._apply(result)

    def _context(self) -> CommandContext:
        return CommandContext(
            api=self.api,
            session=self.session,
            pending_consent=(
                self.pending_consent[1] if self.pending_consent is not None else None
            ),
            pending_action=self.pending_action,
            last_task_id=self.last_task_id,
            help_text=self.registry.help_text,
        )

    def _apply(self, result: CommandResult) -> str:
        if result.session is not _UNSET:
            self.session = cast(SessionView | None, result.session)
        if result.pending_consent is not _UNSET:
            consent = cast(ConsentView | None, result.pending_consent)
            self.pending_consent = (
                (self.session, consent)
                if consent is not None and self.session is not None
                else None
            )
        if result.pending_action is not _UNSET:
            self.pending_action = cast(ActionConfirmationView | None, result.pending_action)
        if result.last_task_id is not _UNSET:
            self.last_task_id = cast(str | None, result.last_task_id)
        return result.text

    def _submit(self, text: str) -> CommandResult:
        if self.session is None:
            return CommandResult("No active session.")
        result = self.api.submit_and_wait(
            SubmitRequest(
                request_id=f"req-{uuid.uuid4().hex[:12]}",
                session_id=self.session.session_id,
                text=text,
            )
        )
        if not result.is_success:
            assert result.failure is not None
            prefix = (
                "Input rejected: "
                if result.failure.code is ApiFailureCode.INVALID_INPUT
                else "Blocked: "
            )
            return CommandResult(prefix + result.failure.safe_message)
        assert result.value is not None
        task = result.value
        pending_consent: ConsentView | None = None
        if task.status is TaskStatus.AWAITING_CONSENT:
            pending = self.api.list_consents()
            if pending.is_success and pending.value is not None:
                pending_consent = next(
                    (proposal for proposal in pending.value if proposal.task_id == task.task_id),
                    None,
                )
        return CommandResult(
            render.render_task_view(task),
            pending_consent=pending_consent,
            pending_action=task.action_confirmation,
            last_task_id=task.task_id,
        )

    # -- interactive loop --------------------------------------------------

    def run(self) -> None:  # pragma: no cover - I/O loop
        print("Elly local-first assistant. Type /help.")
        while True:
            try:
                line = input("\nyou> ")
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                if self.last_task_id is not None:
                    self.api.cancel_task(self.last_task_id)
                print("Cancellation requested.")
                continue
            out = self.dispatch(line)
            if out == EXIT:
                break
            print(out)


__all__ = ["Cli", "EXIT"]

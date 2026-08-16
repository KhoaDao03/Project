"""Cloud-consent and consequential-action decision handlers."""

from __future__ import annotations

from ...api.contracts import (
    ActionDecisionRequest,
    ConsentDecisionRequest,
)
from ...presentation import render
from .base import CommandContext, CommandResult, api_failure


class ConsentDecisionHandler:
    def __init__(self, *, approve: bool) -> None:
        self._approve = approve

    def handle(self, args: tuple[str, ...], context: CommandContext) -> CommandResult:
        result = context.api.decide_consent(ConsentDecisionRequest(args[0], approve=self._approve))
        if not result.is_success:
            return api_failure(result, prefix="Consent decision failed: ")
        assert result.value is not None
        if not self._approve:
            return CommandResult(
                "Consent denied; no specialist call was made.",
                pending_consent=None,
            )
        return CommandResult(
            render.render_task_view(result.value),
            pending_consent=None,
            pending_action=result.value.action_confirmation,
            last_task_id=result.value.task_id,
        )


class ActionDecisionHandler:
    def __init__(self, *, approve: bool) -> None:
        self._approve = approve

    def handle(self, args: tuple[str, ...], context: CommandContext) -> CommandResult:
        result = context.api.decide_action(ActionDecisionRequest(args[0], approve=self._approve))
        if not result.is_success:
            return api_failure(result, prefix="Action confirmation failed: ")
        assert result.value is not None
        return CommandResult(
            render.render_task_view(result.value),
            pending_action=None,
            last_task_id=result.value.task_id,
        )

"""Task, trace, and source command handlers."""

from __future__ import annotations

from ...api.contracts import SourcesQuery, TraceQuery
from .base import CommandArgumentError, CommandContext, CommandResult, api_failure


def one_id(args: tuple[str, ...]) -> tuple[str, ...]:
    if len(args) != 1 or not args[0].strip():
        raise CommandArgumentError("expected one identifier")
    return args


def no_args(args: tuple[str, ...]) -> tuple[str, ...]:
    if args:
        raise CommandArgumentError("expected no arguments")
    return args


class CancelHandler:
    def handle(self, args: tuple[str, ...], context: CommandContext) -> CommandResult:
        if context.last_task_id is None:
            return CommandResult("Cancellation requested.")
        result = context.api.cancel_task(context.last_task_id)
        if not result.is_success:
            return api_failure(result, prefix="Cancellation failed: ")
        return CommandResult("Cancellation requested.")


class TraceHandler:
    def handle(self, args: tuple[str, ...], context: CommandContext) -> CommandResult:
        result = context.api.get_trace(TraceQuery(args[0]))
        if not result.is_success:
            return api_failure(result, prefix="Trace unavailable: ")
        assert result.value is not None
        if not result.value.events:
            return CommandResult("No trace found.")
        routing = (
            "routing "
            f"category={result.value.route_category.value if result.value.route_category else '-'} "
            f"capability={result.value.capability_id or '-'} "
            f"operation={result.value.operation or '-'} "
            f"reason={result.value.selection_reason_code or '-'} "
            f"candidates={result.value.candidate_count} "
            f"rejected={','.join(result.value.rejected_candidate_reason_codes) or 'none'} "
            f"clarification={str(result.value.clarification_required).lower()} "
            f"freshness_affected={str(result.value.freshness_affected_selection).lower()}"
        )
        return CommandResult(
            "\n".join(
                [routing]
                + [
                    f"{event.at.isoformat()} {event.event_type} "
                    f"route={event.route.value if event.route else '-'} "
                    f"status={event.task_status.value if event.task_status else '-'} "
                    f"error={event.error_class or '-'}"
                    + (f" detail={event.detail}" if event.detail else "")
                    for event in result.value.events
                ]
            )
        )


class SourcesHandler:
    def handle(self, args: tuple[str, ...], context: CommandContext) -> CommandResult:
        result = context.api.get_sources(SourcesQuery(args[0]))
        if not result.is_success:
            return api_failure(result, prefix="Sources unavailable: ")
        assert result.value is not None
        return CommandResult("\n".join(result.value.sources) or "No sources found.")

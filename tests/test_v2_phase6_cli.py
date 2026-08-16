"""Phase 6 modular command registry and public-API CLI tests."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

from elly.api.contracts import (
    ApiResult,
    ApplicationStatusView,
    BackupView,
    HistoryView,
    SessionView,
    SourcesView,
    TaskView,
    TraceView,
)
from elly.domain.enums import CloudMode, PersistenceMode, TaskStatus
from elly.presentation.cli import Cli
from elly.presentation.commands import build_command_registry
from elly.presentation.commands.base import CommandContext, CommandDescriptor, CommandResult
from elly.presentation.commands.dispatcher import CommandDispatcher
from elly.presentation.commands.registry import CommandRegistry

UTC = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


class _RegisteredHandler:
    def handle(self, args: tuple[str, ...], context: CommandContext) -> CommandResult:
        return CommandResult("registered:" + ",".join(args))


class _FakePublicApplication:
    def __init__(self) -> None:
        self.session = SessionView(
            "session-fake",
            PersistenceMode.STORE_WITH_RETENTION,
            CloudMode.LOCAL_ONLY,
            UTC,
            UTC,
            1,
        )
        self.mode_calls = []
        self.submit_calls = []

    def create_session(self, request=None):
        return ApiResult.success(self.session)

    def change_session_mode(self, request):
        self.mode_calls.append(request)
        self.session = SessionView(
            self.session.session_id,
            self.session.persistence_mode,
            request.cloud_mode,
            self.session.created_at,
            UTC,
            self.session.version + 1,
        )
        return ApiResult.success(self.session)

    def submit_and_wait(self, request):
        self.submit_calls.append(request)
        return ApiResult.success(
            TaskView(
                "task-fake",
                request.session_id,
                TaskStatus.COMPLETED,
                answer="fake answer",
            )
        )

    def cancel_task(self, task_id):
        return ApiResult.success(TaskView(task_id, self.session.session_id, TaskStatus.CANCELLED))

    def get_profile(self, request=None):
        return ApiResult.success(())

    def change_profile(self, request):
        return ApiResult.success(True)

    def list_history(self, request=None):
        return ApiResult.success(HistoryView((self.session,)))

    def delete_session(self, session_id):
        return ApiResult.success(True)

    def get_trace(self, request):
        return ApiResult.success(TraceView(request.task_id, ()))

    def get_sources(self, request):
        return ApiResult.success(SourcesView(request.task_id, ()))

    def list_consents(self, request=None):
        return ApiResult.success(())

    def decide_consent(self, request):
        return ApiResult.success(
            TaskView("task-fake", self.session.session_id, TaskStatus.COMPLETED)
        )

    def decide_action(self, request):
        return ApiResult.success(
            TaskView("task-fake", self.session.session_id, TaskStatus.COMPLETED)
        )

    def create_backup(self, request):
        return ApiResult.success(BackupView(request.destination))

    def restore_backup(self, request):
        return ApiResult.success(BackupView(request.backup_path, restart_required=True))

    def get_status(self):
        return ApiResult.success(ApplicationStatusView((), ()))

    def close(self):
        return None


class CommandRegistryTests(unittest.TestCase):
    def test_registered_command_executes_without_dispatcher_change(self) -> None:
        registry = CommandRegistry(
            (
                CommandDescriptor(
                    "/probe",
                    "/probe <value>",
                    "run a probe",
                    _RegisteredHandler(),
                ),
            )
        )
        output = CommandDispatcher(registry).dispatch(
            "/probe value",
            CommandContext(api=object(), session=None),  # type: ignore[arg-type]
        )
        self.assertEqual("registered:value", output.text)
        self.assertIn("/probe <value>", registry.help_text())

    def test_registry_rejects_duplicate_names_and_aliases(self) -> None:
        handler = _RegisteredHandler()
        registry = CommandRegistry(
            (CommandDescriptor("/one", "/one", "one", handler, aliases=("/alias",)),)
        )
        with self.assertRaises(ValueError):
            registry.register(CommandDescriptor("/one", "/one", "duplicate", handler))
        with self.assertRaises(ValueError):
            registry.register(
                CommandDescriptor("/two", "/two", "duplicate alias", handler, aliases=("/alias",))
            )
        with self.assertRaises(ValueError):
            registry.register(
                CommandDescriptor(
                    "/three", "/three", "duplicate aliases", handler, aliases=("/x", "/x")
                )
            )

    def test_builtin_help_is_generated_from_registered_commands(self) -> None:
        registry = build_command_registry()
        names = {descriptor.name for descriptor in registry.descriptors()}
        self.assertTrue({"/help", "/status", "/new", "/mode", "/approve", "/deny"} <= names)
        help_text = registry.help_text()
        self.assertIn("/trace <task-id>", help_text)
        self.assertIn("/approve-action <id>", help_text)

    def test_every_builtin_handler_runs_with_the_public_api_only(self) -> None:
        registry = build_command_registry()
        dispatcher = CommandDispatcher(registry)
        api = _FakePublicApplication()
        context = CommandContext(
            api=api,
            session=api.session,
            last_task_id="task-fake",
            help_text=registry.help_text,
        )
        commands = (
            "/help",
            "/new",
            "/mode local",
            "/approve consent-1",
            "/deny consent-1",
            "/approve-action action-1",
            "/deny-action action-1",
            "/profile list",
            "/history list",
            "/trace task-fake",
            "/sources task-fake",
            "/backup backup.db",
            "/restore backup.db",
            "/status",
            "/cancel",
            "/exit",
        )
        for command in commands:
            with self.subTest(command=command):
                result = dispatcher.dispatch(command, context)
                self.assertNotIn("internal application error", result.text)

    def test_unknown_and_invalid_commands_use_consistent_dispatch_errors(self) -> None:
        dispatcher = CommandDispatcher(build_command_registry())
        context = CommandContext(api=_FakePublicApplication(), session=None)
        self.assertEqual(
            "Unknown command: /missing (try /help)",
            dispatcher.dispatch("/missing", context).text,
        )
        invalid = dispatcher.dispatch("/mode maybe", context).text
        self.assertTrue(invalid.startswith("Invalid arguments for /mode:"))
        self.assertIn("Usage: /mode local | /mode cloud", invalid)


class PublicApiCliTests(unittest.TestCase):
    def test_cli_handlers_use_fake_public_api(self) -> None:
        api = _FakePublicApplication()
        cli = Cli.start(api)
        self.assertIn("/status", cli.dispatch("/help"))
        self.assertIn("cloud_permitted", cli.dispatch("/mode cloud"))
        self.assertIn("fake answer", cli.dispatch("hello"))
        self.assertEqual(1, len(api.mode_calls))
        self.assertEqual(1, len(api.submit_calls))

    def test_cli_has_no_legacy_conditional_dispatcher(self) -> None:
        source = Path("src/elly/presentation/cli.py").read_text(encoding="utf-8")
        self.assertNotIn("def _command", source)
        self.assertNotIn(".repository", source)
        self.assertNotIn(".orchestrator", source)
        self.assertNotIn(".profile", source)


if __name__ == "__main__":
    unittest.main()

"""Terminal REPL (FR-001 surface, UC-01/UC-10) — M5.

Design: `Cli.dispatch(line)` maps one input line to output text and is fully
unit-testable without stdin. `Cli.run()` is the thin interactive loop.

M1 commands (DESIGN §6.1 subset):
  plain text        submit a request in the active session
  /new [--no-store] start a clean session (optionally no-store)
  /mode local       set local-only (the only mode with a path in M1)
  /mode cloud       INTENTIONALLY UNAVAILABLE in M2 -> explicit denial (M5)
  /status           dependency health + active mode
  /help             list commands
  /cancel           request cancellation of the active local generation
  /exit             leave

Security: untrusted input is validated before any orchestration (FR-001). Model
output is rendered as data; the CLI never executes anything a model "asks" for.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

from ..composition import Application
from ..domain.enums import CloudMode, PersistenceMode
from ..domain.errors import EllyError, InputInvalidError, PermissionDeniedError
from ..domain.models import AuditEvent, SessionRecord, TaskRequest
from ..domain.enums import TaskStatus
from ..privacy import ConsentProposal
from . import render
from .validators import normalize_and_validate

EXIT = "__EXIT__"

_HELP = """Commands:
  <text>             ask Elly (local generalist or current-information research)
  /new [--no-store]  start a new session
  /mode local        set local-only mode
  /mode cloud        permit policy-controlled hosted web research
  /approve <id>      approve one exact specialist consent proposal
  /deny <id>         deny one specialist consent proposal
  /profile list|add|correct|delete ...
  /history list|delete <session-id>
  /trace <task-id>   show redacted durable task events
  /sources <task-id> show stored source metadata
  /backup <path>     create an encrypted backup
  /restore <path>    restore an encrypted backup
  /status            show dependency health and active mode
  /cancel            request cancellation of the active local generation
  /help              show this help
  /exit              quit"""


@dataclass
class Cli:
    """Interactive terminal for the M3 guarded local assistant."""

    app: Application
    session: SessionRecord
    pending_consent: tuple[TaskRequest, ConsentProposal] | None = None

    @classmethod
    def start(cls, app: Application) -> "Cli":
        return cls(app=app, session=app.new_session())

    # -- single-line dispatch (unit-testable) ------------------------------

    def dispatch(self, line: str) -> str:
        raw = line.strip()
        if not raw:
            # Empty line at the prompt: gentle no-op, no model call (AT-01.2).
            return "(empty input ignored)"
        if raw.startswith("/"):
            return self._command(raw)
        return self._submit(raw)

    def _command(self, raw: str) -> str:
        parts = raw.split()
        cmd, args = parts[0], parts[1:]
        if cmd == "/help":
            return _HELP
        if cmd == "/exit":
            return EXIT
        if cmd == "/status":
            active = f"Mode: {self.session.cloud_mode.value} / {self.session.persistence_mode.value}"
            limits = self.app.config
            guardrails = (
                f"Limits: steps={limits.max_steps}, provider_calls={limits.max_provider_calls}, "
                f"retries={limits.max_retries}, concurrency={limits.max_concurrency}, queue={limits.max_queue_size}, "
                f"timeout={limits.tool_timeout_seconds:g}s/{limits.total_timeout_seconds:g}s"
            )
            spent = self.app.guardrails.cost.reserved_usd if self.app.guardrails else 0.0
            remaining = self.app.guardrails.cost.remaining_usd if self.app.guardrails else 0.0
            warning = self.app.guardrails.cost.warning_level if self.app.guardrails else "unavailable"
            runtime = (
                f"Runtime: generalist={limits.generalist_provider}/{limits.generalist_model_id}; "
                f"research={limits.research_provider}/{limits.research_model_id}; "
                f"specialists={limits.specialist_provider}/{limits.specialist_default_model_id}"
            )
            pricing = (
                f"Pricing: remote reservation=${limits.remote_call_reservation_usd:.4f}/call; "
                f"consent max=${limits.consent_max_cost_usd:.4f}; "
                f"monthly budget=${limits.monthly_budget_usd:.2f}"
            )
            return (
                render.render_health(self.app.health()) + "\n" + active + "\n"
                + runtime + "\n" + pricing + "\n" + guardrails
                + f"\nBudget used/reserved: ${spent:.4f}; remaining: ${remaining:.4f}; warning: {warning}"
            )
        if cmd == "/new":
            no_store = "--no-store" in args
            mode = PersistenceMode.NO_STORE if no_store else PersistenceMode.STORE_WITH_RETENTION
            self.session = self.app.new_session(persistence_mode=mode)
            return f"Started {self.session.session_id} ({mode.value})."
        if cmd == "/mode":
            if args == ["local"]:
                self.session = SessionRecord(
                    session_id=self.session.session_id, persistence_mode=self.session.persistence_mode,
                    cloud_mode=CloudMode.LOCAL_ONLY, created_at=self.session.created_at,
                )
                return "Mode: local_only."
            if args == ["cloud"]:
                self.session = SessionRecord(
                    session_id=self.session.session_id, persistence_mode=self.session.persistence_mode,
                    cloud_mode=CloudMode.CLOUD_PERMITTED, created_at=self.session.created_at,
                )
                return "Mode: cloud_permitted (hosted web research requires OPENAI_API_KEY)."
            return "Usage: /mode local | /mode cloud"
        if cmd == "/cancel":
            self.app.cancel_active()
            return "Cancellation requested."
        if cmd == "/profile":
            return self._profile_command(args)
        if cmd == "/history":
            return self._history_command(args)
        if cmd == "/trace" and len(args) == 1:
            events = self.app.repository.audit_by_task(args[0])
            if not events:
                return "No trace found."
            return "\n".join(
                f"{e.at.isoformat()} {e.event_type} "
                f"route={e.route.value if e.route else '-'} "
                f"status={e.task_status.value if e.task_status else '-'} "
                f"error={e.error_class.value if e.error_class else '-'}"
                + (f" detail={e.detail}" if e.detail else "")
                for e in events
            )
        if cmd == "/sources" and len(args) == 1:
            sources = self.app.repository.task_sources(args[0])
            return "\n".join(sources) if sources else "No sources found."
        if cmd == "/backup" and len(args) == 1:
            if self.app.backup is None:
                return "Backup unavailable: ELLY_BACKUP_KEY is not configured."
            try:
                return f"Backup created: {self.app.backup.create(args[0])}"
            except EllyError as exc:
                return f"Backup failed: {exc.summary}"
        if cmd == "/restore" and len(args) == 1:
            if self.app.backup is None:
                return "Restore unavailable: ELLY_BACKUP_KEY is not configured."
            try:
                self.app.backup.restore(args[0])
                return "Backup restored after integrity validation; restart Elly before using the restored database."
            except EllyError as exc:
                return f"Restore failed: {exc.summary}"
        if cmd in {"/approve", "/deny"}:
            if len(args) != 1 or self.pending_consent is None:
                return f"Usage: {cmd} <proposal-id>"
            request, proposal = self.pending_consent
            proposal_id = proposal.proposal_id
            if args[0] != proposal_id:
                return "Consent proposal does not match the pending task."
            workflow = self.app.specialist_workflow
            if workflow is None:
                return "Specialist capability is unavailable."
            try:
                if cmd == "/deny":
                    workflow.consent.deny(proposal_id)
                    self.app.audit.append(AuditEvent(
                        task_id=f"task-{request.request_id}", session_id=request.session_id,
                        event_type="consent.denied", at=self.app.clock.now(),
                        task_status=TaskStatus.BLOCKED,
                        detail=f"proposal={proposal_id} provider={proposal.provider}",
                    ))
                    self.pending_consent = None
                    return "Consent denied; no specialist call was made."
                workflow.consent.approve(proposal_id)
                approved = replace(request, request_id=f"{request.request_id}-approved", approval_id=proposal_id)
                # Approval must be durable before the external call. An audit
                # failure raises and the call is not submitted (AT-13.4).
                self.app.audit.append(AuditEvent(
                    task_id=f"task-{approved.request_id}", session_id=request.session_id,
                    event_type="consent.approved", at=self.app.clock.now(),
                    task_status=TaskStatus.AWAITING_CONSENT,
                    detail=(f"proposal={proposal_id} provider={proposal.provider} "
                            f"model={proposal.model}")
                ))
                self.pending_consent = None
                future = self.app.submit(approved) if self.app.executor is not None else None
                outcome = future.result() if future is not None else self.app.orchestrator.handle(approved)
                return render.render_result(outcome.result)
            except EllyError as exc:
                return f"Blocked: {exc.summary}"
        return f"Unknown command: {cmd} (try /help)"

    def _profile_command(self, args: list[str]) -> str:
        if not args or args[0] == "list":
            items = self.app.profile.list()
            return "\n".join(f"{item.item_id}: {item.key}={item.value} [{item.sensitivity}] confirmed" for item in items) or "No confirmed profile items."
        if args[0] == "add" and len(args) >= 3 and "=" in args[1]:
            key, value = args[1].split("=", 1)
            item = self.app.profile.add(item_id=args[2], key=key, value=value, sensitivity=args[3] if len(args) > 3 else "local")
            return f"Profile item confirmed: {item.item_id}"
        if args[0] == "correct" and len(args) >= 4 and "=" in args[2]:
            key, value = args[2].split("=", 1)
            item = self.app.profile.correct(args[1], key=key, value=value)
            return f"Profile item corrected: {item.item_id}"
        if args[0] == "delete" and len(args) == 2:
            return "Profile item deleted." if self.app.profile.delete(args[1]) else "Profile item not found."
        return "Usage: /profile list | add key=value item-id [sensitivity] | correct item-id key=value | delete item-id"

    def _history_command(self, args: list[str]) -> str:
        if args == ["list"]:
            sessions = self.app.repository.list_sessions()
            return "\n".join(f"{s.session_id} {s.created_at.isoformat()} {s.persistence_mode.value}" for s in sessions) or "No sessions."
        if len(args) == 2 and args[0] == "delete":
            return "Session deleted." if self.app.repository.delete_session(args[1]) else "Session not found."
        return "Usage: /history list | delete session-id"

    def _submit(self, text: str) -> str:
        try:
            clean = normalize_and_validate(text, max_chars=self.app.config.max_input_chars)
        except InputInvalidError as exc:
            return f"Input rejected: {exc.summary}"

        request = TaskRequest(
            request_id=f"req-{uuid.uuid4().hex[:12]}",
            session_id=self.session.session_id,
            text=clean,
            cloud_mode=self.session.cloud_mode,
            persistence_mode=self.session.persistence_mode,
            submitted_at=self.app.clock.now(),
        )
        try:
            if self.app.executor is None:
                outcome = self.app.orchestrator.handle(request)
            else:
                outcome = self.app.submit(request).result()
        except EllyError as exc:
            # A storage/typed failure that reached the boundary — surface as blocked,
            # never a fabricated success (FR-006). Provider/validation failures are
            # already mapped to a blocked TaskResult inside handle().
            return f"Blocked: {exc.summary}"
        if outcome.consent_proposal is not None:
            self.pending_consent = (request, outcome.consent_proposal)
        return render.render_result(outcome.result)

    # -- interactive loop --------------------------------------------------

    def run(self) -> None:  # pragma: no cover - I/O loop
        print("Elly local-first assistant. Type /help.")
        while True:
            try:
                line = input("you> ")
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                self.app.cancel_active()
                print("Cancellation requested.")
                continue
            out = self.dispatch(line)
            if out == EXIT:
                break
            print(out)

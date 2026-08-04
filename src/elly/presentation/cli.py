"""Terminal REPL (FR-001 surface, UC-01/UC-10 initial) — M2.

Design: `Cli.dispatch(line)` maps one input line to output text and is fully
unit-testable without stdin. `Cli.run()` is the thin interactive loop.

M1 commands (DESIGN §6.1 subset):
  plain text        submit a request in the active session
  /new [--no-store] start a clean session (optionally no-store)
  /mode local       set local-only (the only mode with a path in M1)
  /mode cloud       INTENTIONALLY UNAVAILABLE in M2 -> explicit denial (M5)
  /status           dependency health + active mode
  /help             list commands
  /cancel           Ctrl+C requests local cancellation; full task UI is M3
  /exit             leave

Security: untrusted input is validated before any orchestration (FR-001). Model
output is rendered as data; the CLI never executes anything a model "asks" for.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from ..composition import Application
from ..domain.enums import CloudMode, PersistenceMode
from ..domain.errors import EllyError, InputInvalidError, PermissionDeniedError
from ..domain.models import SessionRecord, TaskRequest
from . import render
from .validators import normalize_and_validate

EXIT = "__EXIT__"

_HELP = """Commands:
  <text>             ask Elly (local, M1 fake generalist)
  /new [--no-store]  start a new session
  /mode local        set local-only mode
  /mode cloud        (unavailable in M2 — cloud specialists arrive in M5)
  /status            show dependency health and active mode
  /cancel            (use Ctrl+C to request local cancellation; full UI is M3)
  /help              show this help
  /exit              quit"""


@dataclass
class Cli:
    """Interactive terminal for the M1 skeleton."""

    app: Application
    session: SessionRecord

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
            return render.render_health(self.app.health()) + "\n" + active
        if cmd == "/new":
            no_store = "--no-store" in args
            mode = PersistenceMode.NO_STORE if no_store else PersistenceMode.STORE_WITH_RETENTION
            self.session = self.app.new_session(persistence_mode=mode)
            return f"Started {self.session.session_id} ({mode.value})."
        if cmd == "/mode":
            if args == ["local"]:
                # local-only is already the M1 default; acknowledge.
                return "Mode: local_only."
            if args == ["cloud"]:
                # Intentionally-unavailable path fails EXPLICITLY (SEC-005/AI-014).
                return "Cloud mode is unavailable in M2; cloud specialists arrive in M5."
            return "Usage: /mode local | /mode cloud"
        if cmd == "/cancel":
            return "No separate cancel command yet; press Ctrl+C during local generation."
        return f"Unknown command: {cmd} (try /help)"

    def _submit(self, text: str) -> str:
        try:
            clean = normalize_and_validate(text, max_chars=self.app.config.max_input_chars)
        except InputInvalidError as exc:
            return f"Input rejected: {exc.summary}"

        request = TaskRequest(
            request_id=f"req-{uuid.uuid4().hex[:12]}",
            session_id=self.session.session_id,
            text=clean,
            cloud_mode=CloudMode.LOCAL_ONLY,
            persistence_mode=self.session.persistence_mode,
            submitted_at=self.app.clock.now(),
        )
        try:
            outcome = self.app.orchestrator.handle(request)
        except EllyError as exc:
            # A storage/typed failure that reached the boundary — surface as blocked,
            # never a fabricated success (FR-006). Provider/validation failures are
            # already mapped to a blocked TaskResult inside handle().
            return f"Blocked: {exc.summary}"
        return render.render_result(outcome.result)

    # -- interactive loop --------------------------------------------------

    def run(self) -> None:  # pragma: no cover - I/O loop
        print("Elly M2 local assistant. Type /help. (Ollama local generalist)")
        while True:
            try:
                line = input("you> ")
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                cancel = getattr(self.app.generalist, "cancel", None)
                if callable(cancel):
                    cancel()
                    print("Cancellation requested.")
                else:
                    print()
                continue
            out = self.dispatch(line)
            if out == EXIT:
                break
            print(out)

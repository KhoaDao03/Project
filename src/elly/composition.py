"""Composition root — wires config, adapters, and the orchestrator (M1).

This is the ONE place that knows which concrete adapters back each port. Swapping
the FakeGeneralist for the real Ollama adapter in M2 happens HERE plus config —
nothing in domain/application changes (NFR-006). Keeping wiring isolated is what
makes the ports/adapters boundary real rather than decorative.

Status: Scaffolded + Tested (M1, "Agent implements").
"""

from __future__ import annotations

import logging
import uuid

from .adapters.audit_log import StructuredAuditLog
from .adapters.fake_generalist import FakeGeneralist
from .adapters.sqlite_repository import SqliteSessionRepository
from .adapters.system_clock import SystemClock
from .application.conversation import ConversationOrchestrator
from .config import Config, load_config
from .domain.enums import CloudMode, HealthState, PersistenceMode
from .domain.models import HealthReport, SessionRecord
from .ports.audit import AuditPort
from .ports.clock import ClockPort
from .ports.generalist import GeneralistPort
from .ports.repository import SessionRepositoryPort


class Application:
    """Wired M1 application container.

    Holds the composed collaborators and exposes the small surface the CLI needs.
    Construct via `build()`.
    """

    def __init__(
        self,
        *,
        config: Config,
        clock: ClockPort,
        generalist: GeneralistPort,
        repository: SessionRepositoryPort,
        audit: AuditPort,
    ) -> None:
        self.config = config
        self.clock = clock
        self.generalist = generalist
        self.repository = repository
        self.audit = audit
        self.orchestrator = ConversationOrchestrator(
            clock=clock,
            generalist=generalist,
            repository=repository,
            audit=audit,
            context_window=config.context_window_messages,
            model_id=config.generalist_model_id,
            max_output_tokens=config.generalist_max_output_tokens,
        )

    # -- session lifecycle -------------------------------------------------

    def new_session(
        self,
        *,
        persistence_mode: PersistenceMode = PersistenceMode.STORE_WITH_RETENTION,
        cloud_mode: CloudMode = CloudMode.LOCAL_ONLY,
    ) -> SessionRecord:
        """Create and persist a fresh session; returns the record."""
        record = SessionRecord(
            session_id=f"session-{uuid.uuid4().hex[:12]}",
            persistence_mode=persistence_mode,
            cloud_mode=cloud_mode,
            created_at=self.clock.now(),
        )
        self.repository.create_session(record)
        return record

    # -- health (OPS-002 initial) -----------------------------------------

    def close(self) -> None:
        """Release resources (the SQLite connection). Safe to call once at shutdown."""
        close = getattr(self.repository, "close", None)
        if callable(close):
            close()

    def health(self) -> list[HealthReport]:
        """Report each dependency's health for `/status`. Never exposes secrets."""
        reports = [self.generalist.health()]
        # Storage health: a trivial read proves the connection/schema is usable.
        try:
            self.repository.recent_messages("___healthcheck___", 1)
            reports.append(HealthReport(component="storage(sqlite)", state=HealthState.HEALTHY))
        except Exception as exc:  # noqa: BLE001 - report, do not crash /status
            reports.append(
                HealthReport(
                    component="storage(sqlite)",
                    state=HealthState.UNAVAILABLE,
                    detail=type(exc).__name__,
                )
            )
        reports.append(HealthReport(component="audit", state=HealthState.HEALTHY))
        return reports


def build(toml_path: str | None = None) -> Application:
    """Build the fully-wired M1 application.

    Real vs fake in this wiring:
      - generalist: FakeGeneralist (DETERMINISTIC FAKE; real Ollama is M2).
      - repository: SqliteSessionRepository (REAL persistence).
      - audit:      StructuredAuditLog (REAL, redacted, non-durable).
      - clock:      SystemClock (REAL).
    """
    config = load_config(toml_path)
    logging.basicConfig(level=getattr(logging, config.log_level, logging.INFO))

    repository = SqliteSessionRepository(config.db_path)
    repository.apply_migrations()

    app = Application(
        config=config,
        clock=SystemClock(),
        generalist=FakeGeneralist(model_id=config.generalist_model_id),
        repository=repository,
        audit=StructuredAuditLog(),
    )
    return app

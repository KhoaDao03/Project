"""Composition root — wires config, adapters, guardrails, registry, and orchestrator (M6).

This is the ONE place that knows which concrete adapters back each port. Swapping
the FakeGeneralist for the real Ollama adapter in M2 happens HERE plus config —
nothing in domain/application changes (NFR-006). Keeping wiring isolated is what
makes the ports/adapters boundary real rather than decorative.

Status: Implemented + Tested (M6).
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from concurrent.futures import Future
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .api.application import EllyApplication

from .adapters.audit_log import StructuredAuditLog
from .adapters.fake_generalist import FakeGeneralist
from .adapters.http_document_retriever import HttpDocumentRetriever
from .adapters.ollama_generalist import OllamaGeneralist
from .adapters.openai_specialist import OpenAISpecialistProvider
from .adapters.openai_web_research import OpenAIHostedWebSearch
from .adapters.sqlite_repository import SqliteSessionRepository
from .adapters.system_clock import SystemClock
from .application.action_authorization import ActionAuthorizationService
from .application.authorization import CloudAuthorizationPolicy
from .application.capabilities import CapabilityRegistry
from .application.capability_handlers import (
    ResearchCapabilityHandler,
    SpecialistCapabilityHandler,
)
from .application.capability_workflow import CapabilityExecutionWorkflow
from .application.completion import CompletionService
from .application.context_builder import ContextBuilder
from .application.conversation import ConversationOrchestrator
from .application.local_conversation import LocalConversationUseCase
from .application.research import ResearchPipeline
from .application.routing import RoutingPolicy
from .application.specialist_policy import SpecialistExecutionPolicy
from .application.specialists import SpecialistWorkflow
from .config import Config, load_config
from .domain.enums import CloudMode, HealthState, PersistenceMode
from .domain.errors import ConfigInvalidError
from .domain.models import ConversationOutcome, HealthReport, SessionRecord, TaskRequest
from .guardrails import BoundedTaskExecutor, GuardrailController, LimitPolicy
from .memory import ProfileService
from .operations import BackupService
from .ports.audit import AuditPort
from .ports.clock import ClockPort
from .ports.generalist import GeneralistPort
from .ports.repository import SessionRepositoryPort
from .privacy import ConsentWorkflow, PrivacyPolicy
from .research.evidence_policy import EvidencePolicy
from .research.fake_provider import FixtureWebResearchProvider
from .specialists.fake_provider import FakeSpecialistProvider
from .specialists.registry import SpecialistRegistry


def validate_required_dependencies(
    *,
    clock: ClockPort,
    generalist: GeneralistPort,
    repository: SessionRepositoryPort,
    audit: AuditPort,
) -> None:
    """Fail early when a required application port is missing or incompatible."""
    required = (
        ("clock", clock, ClockPort),
        ("generalist", generalist, GeneralistPort),
        ("repository", repository, SessionRepositoryPort),
        ("audit", audit, AuditPort),
    )
    for name, dependency, protocol in required:
        if dependency is None or not isinstance(dependency, protocol):
            raise ConfigInvalidError(
                f"required dependency {name} does not implement {protocol.__name__}"
            )


def _specialist_capability_handlers(
    specialist_registry: SpecialistRegistry,
    specialist_workflow: SpecialistWorkflow | None,
) -> tuple[SpecialistCapabilityHandler, ...]:
    """Adapt valid manifests into registry-backed capability handlers."""
    return tuple(
        SpecialistCapabilityHandler(
            manifest.id,
            manifest,
            specialist_workflow,
        )
        for manifest in specialist_registry.all()
    )


class Application:
    """Wired M6 application container.

    Holds the composed collaborators and exposes the small surface the CLI needs.
    Construct via `build()`.
    """

    def cancel_active(self) -> bool:
        """Cancel the active local or hosted operation through its provider port."""
        return self.orchestrator.cancel_active()

    def cancel_task(self, task_id: str) -> bool:
        """Cancel one identified in-flight operation through its provider port."""
        return self.orchestrator.cancel_task(task_id)

    def __init__(
        self,
        *,
        config: Config,
        clock: ClockPort,
        generalist: GeneralistPort,
        repository: SessionRepositoryPort,
        audit: AuditPort,
        specialist_registry: SpecialistRegistry | None = None,
        guardrails: GuardrailController | None = None,
        executor: BoundedTaskExecutor | None = None,
        local_conversation: LocalConversationUseCase | None = None,
        capability_workflow: CapabilityExecutionWorkflow | None = None,
        completion: CompletionService | None = None,
        research: ResearchPipeline | None = None,
        specialist_workflow: SpecialistWorkflow | None = None,
        consent: ConsentWorkflow | None = None,
        capability_registry: CapabilityRegistry | None = None,
        action_authorization: ActionAuthorizationService | None = None,
    ) -> None:
        self.config = config
        validate_required_dependencies(
            clock=clock, generalist=generalist, repository=repository, audit=audit
        )
        # Composition is also the startup boundary: an un-migrated or damaged
        # store must fail before the CLI accepts work.
        repository.healthcheck()
        self.clock = clock
        self.generalist = generalist
        self.repository = repository
        self.audit = audit
        self.specialist_registry = specialist_registry or SpecialistRegistry()
        self.guardrails = guardrails
        self.executor = executor
        self.research = research
        self.specialist_workflow = specialist_workflow
        self.consent = consent
        self.local_conversation = local_conversation or LocalConversationUseCase(
            generalist=generalist,
            model_id=config.generalist_model_id,
            max_output_tokens=config.generalist_max_output_tokens,
            guardrails=guardrails,
        )
        self.capability_registry = capability_registry or CapabilityRegistry()
        self.capability_registry.validate()
        self.routing_policy = RoutingPolicy(
            capabilities=self.capability_registry,
        )
        self.privacy_policy = PrivacyPolicy()
        self.cloud_authorization_policy = CloudAuthorizationPolicy()
        self.action_authorization = action_authorization or ActionAuthorizationService()
        self.completion = completion or CompletionService(
            clock=clock,
            repository=repository,
            audit=audit,
        )
        self.capability_workflow = capability_workflow or CapabilityExecutionWorkflow(
            clock=clock,
            capability_registry=self.capability_registry,
            completion=self.completion,
            consent=consent,
            privacy_policy=self.privacy_policy,
            cloud_authorization_policy=self.cloud_authorization_policy,
            action_authorization=self.action_authorization,
        )
        self.context_builder = ContextBuilder(
            context_window=config.context_window_messages,
            reserved_output_tokens=config.generalist_max_output_tokens,
        )
        self.profile = ProfileService(repository, clock)
        self.backup: BackupService | None = None
        self._maintenance_stop = threading.Event()
        self._maintenance_thread: threading.Thread | None = None
        self.orchestrator = ConversationOrchestrator(
            clock=clock,
            repository=repository,
            audit=audit,
            context_window=config.context_window_messages,
            local_conversation=self.local_conversation,
            completion=self.completion,
            capability_workflow=self.capability_workflow,
            guardrails=guardrails,
            profile_service=self.profile,
            routing_policy=self.routing_policy,
            context_builder=self.context_builder,
        )

    # -- session lifecycle -------------------------------------------------

    def new_session(
        self,
        *,
        persistence_mode: PersistenceMode = PersistenceMode.STORE_WITH_RETENTION,
        cloud_mode: CloudMode = CloudMode.LOCAL_ONLY, # CloudMode.CLOUD_PERMITTED
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
        self._maintenance_stop.set()
        if self._maintenance_thread is not None:
            self._maintenance_thread.join(timeout=2)
        if self.executor is not None:
            self.executor.shutdown()
        self.repository.close()

    def maintain_storage(self) -> None:
        """Apply configured retention and create a daily backup when enabled."""
        from datetime import timedelta
        now = self.clock.now()
        self.repository.purge_sessions(
            now - timedelta(days=self.config.session_retention_days)
        )
        self.profile.load_startup()
        self.repository.purge_task_sources(
            now - timedelta(days=self.config.evidence_retention_days)
        )
        self.repository.purge_task_provenance(
            now - timedelta(days=self.config.evidence_retention_days)
        )
        self.repository.purge_audit_events(
            now - timedelta(days=self.config.audit_retention_days)
        )
        if self.backup is not None:
            self.backup.create_daily_if_due(self.config.backup_dir, now=now)

    def start_maintenance_scheduler(self, *, interval_seconds: float = 3600.0) -> None:
        """Run retention and daily-backup checks periodically until shutdown."""
        if interval_seconds <= 0:
            raise ValueError("maintenance interval must be positive")
        if self._maintenance_thread is not None:
            return

        def run() -> None:
            while not self._maintenance_stop.wait(interval_seconds):
                try:
                    self.maintain_storage()
                except Exception as exc:  # noqa: BLE001 - keep future maintenance alive
                    logging.getLogger("elly.maintenance").error(
                        "maintenance failed error=%s", type(exc).__name__
                    )

        self._maintenance_thread = threading.Thread(
            target=run, name="elly-maintenance", daemon=True
        )
        self._maintenance_thread.start()

    def health(self) -> list[HealthReport]:
        """Report each dependency's health for `/status`. Never exposes secrets."""
        reports = [self.generalist.health()]
        if self.research is not None:
            reports.append(self.research.provider.health())
        if self.specialist_workflow is not None:
            reports.append(self.specialist_workflow.provider.health())
        # Storage health: a trivial read proves the connection/schema is usable.
        try:
            self.repository.healthcheck()
            reports.append(HealthReport(component="storage(sqlite)", state=HealthState.HEALTHY))
        except Exception as exc:  # noqa: BLE001 - report, do not crash /status
            reports.append(
                HealthReport(
                    component="storage(sqlite)",
                    state=HealthState.UNAVAILABLE,
                    detail=type(exc).__name__,
                )
            )
        reports.append(
            self.audit.health()
        )
        reports.append(HealthReport(
            component="profile",
            state=HealthState.DEGRADED if self.profile.degraded else HealthState.HEALTHY,
            detail="corrupt profile quarantined" if self.profile.degraded else "",
        ))
        return reports

    def submit(self, request: TaskRequest) -> Future[ConversationOutcome]:
        """Submit a conversation through bounded local admission."""
        if self.executor is None:
            raise RuntimeError("task executor is not configured")
        return self.executor.submit(lambda: self.orchestrator.handle(request))


def build(toml_path: str | None = None) -> Application:
    """Build the fully-wired M6 application.

    Real vs fake in this wiring:
      - generalist: configured fake or real localhost Ollama.
      - research: approved OpenAI hosted web_search or deterministic fixtures.
      - repository: SqliteSessionRepository (REAL persistence).
      - audit:      StructuredAuditLog (REAL, redacted, durable metadata).
      - clock:      SystemClock (REAL).
    """
    config = load_config(toml_path)
    logging.basicConfig(level=logging._nameToLevel.get(config.log_level, logging.INFO))

    repository = SqliteSessionRepository(config.db_path)
    repository.apply_migrations()
    repository.mark_interrupted_tasks(SystemClock().now())

    guardrails = GuardrailController(
        policy=LimitPolicy(
            max_steps=config.max_steps,
            max_provider_calls=config.max_provider_calls,
            max_retries=config.max_retries,
            max_concurrency=config.max_concurrency,
            monthly_budget_usd=config.monthly_budget_usd,
            max_output_tokens=max(
                config.generalist_max_output_tokens,
                config.specialist_max_output_tokens,
                config.research_max_output_tokens,
            ),
        ),
        tool_timeout_seconds=config.tool_timeout_seconds,
        total_timeout_seconds=config.total_timeout_seconds,
        provider_call_cost_usd=0.0,
    )
    executor = BoundedTaskExecutor(workers=config.max_concurrency, queue_size=config.max_queue_size)
    research_provider = (
        FixtureWebResearchProvider()
        if config.research_provider == "fixtures"
        else OpenAIHostedWebSearch(
            model=config.research_model_id,
            max_output_tokens=config.research_max_output_tokens,
        )
    )
    research = ResearchPipeline(
        provider=research_provider, clock=SystemClock(), max_results=config.research_max_results,
        timeout_seconds=config.research_timeout_seconds,
        max_output_tokens=config.research_max_output_tokens,
        guardrails=guardrails,
        resolve_hosts=config.research_provider == "openai_web_search",
        call_cost_usd=(
            config.remote_call_reservation_usd
            if config.research_provider == "openai_web_search" else 0.0
        ),
        evidence_policy=EvidencePolicy(
            retriever=(
                HttpDocumentRetriever()
                if config.research_provider == "openai_web_search" else None
            ),
            retrieval_timeout_seconds=min(config.research_timeout_seconds, 15.0),
        ),
    )
    consent = ConsentWorkflow()
    specialist_provider = (
        FakeSpecialistProvider()
        if config.specialist_provider == "fake"
        else OpenAISpecialistProvider(
            cost_per_call_usd=config.remote_call_reservation_usd
        )
    )
    specialist_workflow = SpecialistWorkflow(
        provider=specialist_provider,
        policy=SpecialistExecutionPolicy(
            max_output_tokens=config.specialist_max_output_tokens,
        ),
        guardrails=guardrails,
        provider_name=config.specialist_provider,
        call_cost_usd=(
            config.remote_call_reservation_usd
            if config.specialist_provider == "openai" else 0.0
        ),
        consent_max_cost_usd=config.consent_max_cost_usd,
    )

    specialist_registry = SpecialistRegistry.from_directory(
        config.specialist_manifest_dir,
        default_model=config.specialist_default_model_id,
        model_overrides=dict(config.specialist_model_overrides),
    )
    capability_registry = CapabilityRegistry(
        (
            ResearchCapabilityHandler(
                research,
                provider_id=config.research_provider,
                model_id=config.research_model_id,
                max_cost_usd=config.consent_max_cost_usd,
            ),
            *_specialist_capability_handlers(specialist_registry, specialist_workflow),
        )
    )

    app = Application(
        config=config,
        clock=SystemClock(),
        generalist=(
            FakeGeneralist(model_id=config.generalist_model_id)
            if config.generalist_provider == "fake"
            else OllamaGeneralist(
                base_url=config.ollama_base_url,
                timeout_seconds=config.ollama_timeout_seconds,
            )
        ),
        repository=repository,
        audit=StructuredAuditLog(repository=repository),
        specialist_registry=specialist_registry,
        guardrails=guardrails,
        executor=executor,
        research=research,
        specialist_workflow=specialist_workflow,
        consent=consent,
        capability_registry=capability_registry,
    )
    if os.environ.get("ELLY_BACKUP_KEY"):
        app.backup = BackupService(db_path=config.db_path)
    app.maintain_storage()
    app.start_maintenance_scheduler()
    return app


def build_application(toml_path: str | None = None) -> "EllyApplication":
    """Build the public V2 façade over the composed application scope."""
    from .api.application import EllyApplication

    return EllyApplication(build(toml_path))

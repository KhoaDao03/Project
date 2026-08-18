"""Composition root — wires config, adapters, guardrails, registry, and runtime.

This is the ONE place that knows which concrete adapters back each port. Swapping
the FakeGeneralist for the real Ollama adapter in M2 happens HERE plus config —
nothing in domain/application changes (NFR-006). Keeping wiring isolated is what
makes the ports/adapters boundary real rather than decorative.

Status: Implemented + Tested.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from .api.application import EllyApplication

from .adapters.audit_log import StructuredAuditLog
from .adapters.fake_generalist import FakeGeneralist
from .adapters.fake_planner import FakePlanner, PlannerFailureMode
from .adapters.fake_response_composer import FakeResponseComposer
from .adapters.http_document_retriever import HttpDocumentRetriever
from .adapters.ollama_generalist import OllamaGeneralist
from .adapters.ollama_planner import OllamaPlanner
from .adapters.ollama_response_composer import OllamaResponseComposer
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
from .application.local_conversation import LocalConversationUseCase
from .application.local_conversation_capability import (
    LOCAL_CONVERSATION_CAPABILITY_ID,
    LocalConversationCapabilityHandler,
)
from .application.plan_builder import PlanBuilder
from .application.plan_interpreter import PlanInterpreter
from .application.planning_service import PlanningService
from .application.recovery import PlanRecovery
from .application.replan import (
    ReplanService,
)
from .application.research import ResearchPipeline
from .application.response_pipeline import ResponseCompositionService
from .application.routing import RoutingPolicy
from .application.runtime import AssistantRuntime
from .application.specialist_policy import SpecialistExecutionPolicy
from .application.specialists import SpecialistWorkflow
from .application.task_execution import TaskExecutionService
from .config import Config, load_config
from .domain.enums import HealthState
from .domain.errors import ConfigInvalidError
from .domain.models import HealthReport
from .guardrails import BoundedTaskExecutor, GuardrailController, LimitPolicy
from .memory import ProfileService
from .operations import BackupService
from .ports.audit import AuditPort
from .ports.clock import ClockPort
from .ports.generalist import GeneralistPort
from .ports.local_planner import LocalPlannerPort
from .ports.local_response_composer import LocalResponseComposerPort
from .ports.plan_repository import PlanRepositoryPort
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
    """Wired application container.

    Holds the composed collaborators and exposes the small surface the CLI needs.
    Construct via `build()`.
    """

    @property
    def audit(self) -> AuditPort:
        return self._audit

    @audit.setter
    def audit(self, value: AuditPort) -> None:
        # Compatibility callers may replace the audit port after composition;
        # keep the runtime's completion boundary on the same port.
        self._audit = value
        completion = getattr(self, "completion", None)
        if completion is not None:
            completion._audit = value

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
        planner: LocalPlannerPort | None = None,
        response_composer: LocalResponseComposerPort | None = None,
        planning_service: PlanningService | None = None,
        task_execution_service: TaskExecutionService | None = None,
        replan_service: ReplanService | None = None,
        recovery: PlanRecovery | None = None,
    ) -> None:
        self.config = config
        validate_required_dependencies(
            clock=clock, generalist=generalist, repository=repository, audit=audit
        )
        # Composition is also the startup boundary: an un-migrated or damaged
        # store must fail before the CLI accepts work.
        repository.healthcheck()
        if not isinstance(repository, PlanRepositoryPort):
            raise ConfigInvalidError("repository does not implement the plan repository port")
        self.clock = clock
        self.generalist = generalist
        self.repository = repository
        self.plan_repository = cast(PlanRepositoryPort, repository)
        self.audit = audit
        self.specialist_registry = specialist_registry or SpecialistRegistry()
        self.guardrails = guardrails
        self.executor = executor
        self.research = research
        self.specialist_workflow = specialist_workflow
        self.consent = consent
        self.local_conversation = local_conversation or LocalConversationUseCase(
            generalist=generalist,
            model_id=config.conversation_role.model_id,
            max_output_tokens=config.conversation_role.max_output_tokens,
            guardrails=guardrails,
        )
        self.capability_registry = capability_registry or CapabilityRegistry()
        if self.capability_registry.get(LOCAL_CONVERSATION_CAPABILITY_ID) is None:
            self.capability_registry.register(
                LocalConversationCapabilityHandler(self.local_conversation)
            )
        self.capability_registry.validate()
        replan_builder = PlanBuilder(
            self.capability_registry.routing_catalog(),
            config.execution_plan_limits(),
            default_timeout_seconds=config.tool_timeout_seconds,
            synthesis_timeout_seconds=config.response_composer_role.timeout_seconds,
            legacy_synthesis_enabled=False,
        )
        self.replan_service = replan_service or ReplanService(
            repository=self.plan_repository,
            plan_builder=replan_builder,
            clock=clock,
            catalog_provider=self.capability_registry.routing_catalog,
        )
        self.routing_policy = RoutingPolicy(
            capabilities=self.capability_registry,
        )
        # ``build`` supplies the role-bound real/fake adapter.  The direct
        # constructor keeps a deterministic fake for older tests and embedded
        # callers that construct the application without the composition root.
        self.planner = planner if planner is not None else FakePlanner()
        self.response_composer = response_composer
        self.response_pipeline = ResponseCompositionService(
            composer=response_composer,
            max_output_tokens=config.response_composer_role.max_output_tokens,
            timeout_seconds=config.response_composer_role.timeout_seconds,
            profile=config.response_composer_role.profile_name,
            model_version=config.response_composer_role.model_id,
        )
        plan_interpreter = PlanInterpreter(
            planner=self.planner,
            capabilities=self.capability_registry,
            max_output_tokens=config.planner_role.max_output_tokens,
            timeout_seconds=config.planner_role.timeout_seconds,
            routing_policy=self.routing_policy,
        )
        if (
            planning_service is not None
            and planning_service.capabilities is not self.capability_registry
        ):
            raise ConfigInvalidError(
                "planning service must use the application capability registry"
            )
        self.planning_service = planning_service or PlanningService(
            interpreter=plan_interpreter,
            capabilities=self.capability_registry,
            limits=config.execution_plan_limits(),
            default_timeout_seconds=config.tool_timeout_seconds,
            response_timeout_seconds=config.response_composer_role.timeout_seconds,
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
            response_pipeline=self.response_pipeline,
        )
        self.task_execution_service = task_execution_service or TaskExecutionService(
            repository=self.plan_repository,
            capability_registry=self.capability_registry,
            capability_workflow=self.capability_workflow,
            clock=clock,
            max_workers=config.max_parallel_steps,
            response_composer_port=response_composer,
            response_composer_max_output_tokens=config.response_composer_role.max_output_tokens,
            response_composer_timeout_seconds=config.response_composer_role.timeout_seconds,
            response_pipeline=self.response_pipeline,
            recovery=recovery,
            replan_service=self.replan_service,
        )
        self.context_builder = ContextBuilder(
            context_window=config.context_window_messages,
            reserved_output_tokens=config.conversation_role.max_output_tokens,
        )
        self.runtime = AssistantRuntime(
            clock=clock,
            repository=repository,
            plan_repository=self.plan_repository,
            planning_service=self.planning_service,
            task_execution_service=self.task_execution_service,
            context_builder=self.context_builder,
            completion=self.completion,
            response_pipeline=self.response_pipeline,
            local_conversation=self.local_conversation,
            consent=self.consent,
            action_authorization=self.action_authorization,
            context_window=config.context_window_messages,
            guardrails=guardrails,
            executor=executor,
        )
        self.profile = ProfileService(repository, clock)
        self.backup: BackupService | None = None
        self._maintenance_stop = threading.Event()
        self._maintenance_thread: threading.Thread | None = None

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
        self.repository.purge_sessions(now - timedelta(days=self.config.session_retention_days))
        self.profile.load_startup()
        self.repository.purge_task_sources(
            now - timedelta(days=self.config.evidence_retention_days)
        )
        self.repository.purge_task_provenance(
            now - timedelta(days=self.config.evidence_retention_days)
        )
        self.repository.purge_audit_events(now - timedelta(days=self.config.audit_retention_days))
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
        reports.append(
            self.response_composer.health()
            if self.response_composer is not None
            else HealthReport(
                component="response_composer",
                state=HealthState.UNAVAILABLE,
                detail="response composer is not configured",
            )
        )
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
        reports.append(self.audit.health())
        reports.append(
            HealthReport(
                component="profile",
                state=HealthState.DEGRADED if self.profile.degraded else HealthState.HEALTHY,
                detail="corrupt profile quarantined" if self.profile.degraded else "",
            )
        )
        return reports

def build(toml_path: str | None = None) -> Application:
    """Build the fully-wired application.

    Real vs fake in this wiring:
      - generalist: configured fake or real localhost Ollama.
      - planner: configured fake or real localhost Ollama through the planner role.
      - research: approved OpenAI hosted web_search or deterministic fixtures.
      - repository: SqliteSessionRepository (REAL persistence).
      - audit:      StructuredAuditLog (REAL, redacted, durable metadata).
      - clock:      SystemClock (REAL).
    """
    config = load_config(toml_path)
    logging.basicConfig(level=logging._nameToLevel.get(config.log_level, logging.INFO))

    repository = SqliteSessionRepository(config.db_path)
    repository.apply_migrations()
    startup_clock = SystemClock()
    repository.mark_interrupted_tasks(startup_clock.now())
    PlanRecovery(clock=startup_clock).reconcile_startup(repository)

    guardrails = GuardrailController(
        policy=LimitPolicy(
            max_steps=config.max_steps,
            max_provider_calls=config.max_provider_calls,
            max_retries=config.max_retries,
            max_concurrency=config.max_concurrency,
            monthly_budget_usd=config.monthly_budget_usd,
            max_output_tokens=max(
                config.conversation_role.max_output_tokens,
                config.planner_role.max_output_tokens,
                config.response_composer_role.max_output_tokens,
                config.specialist_max_output_tokens,
                config.research_max_output_tokens,
            ),
        ),
        tool_timeout_seconds=config.tool_timeout_seconds,
        total_timeout_seconds=config.total_timeout_seconds,
        remote_call_reservation_usd=0.0,
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
        provider=research_provider,
        clock=SystemClock(),
        max_results=config.research_max_results,
        timeout_seconds=config.research_timeout_seconds,
        max_output_tokens=config.research_max_output_tokens,
        guardrails=guardrails,
        resolve_hosts=config.research_provider == "openai_web_search",
        call_cost_usd=(
            config.remote_call_reservation_usd
            if config.research_provider == "openai_web_search"
            else 0.0
        ),
        evidence_policy=EvidencePolicy(
            retriever=(
                HttpDocumentRetriever() if config.research_provider == "openai_web_search" else None
            ),
            retrieval_timeout_seconds=min(config.research_timeout_seconds, 15.0),
        ),
    )
    consent = ConsentWorkflow()
    specialist_provider = (
        FakeSpecialistProvider()
        if config.specialist_provider == "fake"
        else OpenAISpecialistProvider(cost_per_call_usd=config.remote_call_reservation_usd)
    )
    specialist_workflow = SpecialistWorkflow(
        provider=specialist_provider,
        policy=SpecialistExecutionPolicy(
            max_output_tokens=config.specialist_max_output_tokens,
        ),
        guardrails=guardrails,
        provider_name=config.specialist_provider,
        call_cost_usd=(
            config.remote_call_reservation_usd if config.specialist_provider == "openai" else 0.0
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
            FakeGeneralist(model_id=config.conversation_role.model_id)
            if config.conversation_role.provider == "fake"
            else OllamaGeneralist(
                base_url=config.conversation_role.base_url,
                timeout_seconds=config.conversation_role.timeout_seconds,
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
        planner=(
            # The fake has no semantic interpretation capability. Production
            # composition therefore exercises the deterministic catalog
            # fallback instead of falsely forcing every request local.
            FakePlanner(failure=PlannerFailureMode.MALFORMED)
            if config.planner_role.provider == "fake"
            else OllamaPlanner(role=config.planner_role)
        ),
        response_composer=(
            FakeResponseComposer()
            if config.response_composer_role.provider == "fake"
            else OllamaResponseComposer(role=config.response_composer_role)
        ),
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

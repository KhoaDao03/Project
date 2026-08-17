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
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from .api.application import EllyApplication

from .adapters.audit_log import StructuredAuditLog
from .adapters.fake_generalist import FakeGeneralist
from .adapters.fake_planner import FakePlanner, PlannerFailureMode
from .adapters.fake_response_composer import FakeResponseComposer
from .adapters.fake_synthesis import FakeSynthesis
from .adapters.http_document_retriever import HttpDocumentRetriever
from .adapters.ollama_generalist import OllamaGeneralist
from .adapters.ollama_planner import OllamaPlanner
from .adapters.ollama_response_composer import OllamaResponseComposer
from .adapters.ollama_synthesis import OllamaSynthesis
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
from .application.execution import CancellationToken
from .application.local_conversation import LocalConversationUseCase
from .application.plan_builder import PlanBuilder
from .application.plan_executor import PlanExecutionResult, PlanExecutor
from .application.plan_interpreter import PlanInterpreter
from .application.plan_orchestrator import PlanOrchestrator
from .application.recovery import PlanRecovery, RecoveryReport
from .application.replan import (
    ReplanRequest,
    ReplanResult,
    ReplanService,
    ReplanTrigger,
)
from .application.research import ResearchPipeline
from .application.response_pipeline import ResponseCompositionService
from .application.routing import RoutingPolicy
from .application.specialist_policy import SpecialistExecutionPolicy
from .application.specialists import SpecialistWorkflow
from .config import Config, load_config
from .domain.context import resolve_conversation_context
from .domain.enums import CloudMode, HealthState, PersistenceMode
from .domain.errors import ConfigInvalidError, PlanValidationError
from .domain.models import (
    ContextManifest,
    ConversationOutcome,
    HealthReport,
    Message,
    RouteRequest,
    SessionRecord,
    TaskRequest,
)
from .guardrails import BoundedTaskExecutor, GuardrailController, LimitPolicy
from .memory import ProfileService
from .operations import BackupService
from .planning.contracts import ExecutionPlan, ExecutionProposal, ProposalDisposition
from .ports.audit import AuditPort
from .ports.clock import ClockPort
from .ports.generalist import GeneralistPort
from .ports.local_planner import LocalPlannerPort
from .ports.local_response_composer import LocalResponseComposerPort
from .ports.local_synthesis import LocalSynthesisPort
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
    """Wired M6 application container.

    Holds the composed collaborators and exposes the small surface the CLI needs.
    Construct via `build()`.
    """

    def cancel_active(self) -> bool:
        """Cancel the active local or hosted operation through its provider port."""
        return self.plan_orchestrator.cancel_active() or self.orchestrator.cancel_active()

    def cancel_task(self, task_id: str) -> bool:
        """Cancel one identified in-flight operation through its provider port."""
        return self.plan_orchestrator.cancel_task(task_id) or self.orchestrator.cancel_task(task_id)

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
        synthesis: LocalSynthesisPort | None = None,
        response_composer: LocalResponseComposerPort | None = None,
        plan_builder: PlanBuilder | None = None,
        plan_executor: PlanExecutor | None = None,
        plan_orchestrator: PlanOrchestrator | None = None,
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
        self._planning_enabled = planner is not None
        self._v3_authorization_lock = threading.RLock()
        self._v3_authorization_steps: dict[str, tuple[str, str]] = {}
        self._v3_execution_context: dict[str, tuple[str, ContextManifest]] = {}
        self.local_conversation = local_conversation or LocalConversationUseCase(
            generalist=generalist,
            model_id=config.conversation_role.model_id,
            max_output_tokens=config.conversation_role.max_output_tokens,
            guardrails=guardrails,
        )
        self.capability_registry = capability_registry or CapabilityRegistry()
        self.capability_registry.validate()
        self.plan_builder = plan_builder or PlanBuilder(
            self.capability_registry.routing_catalog(),
            config.execution_plan_limits(),
            default_timeout_seconds=config.tool_timeout_seconds,
            synthesis_timeout_seconds=config.response_composer_role.timeout_seconds,
            legacy_synthesis_enabled=response_composer is None,
        )
        self.replan_service = replan_service or ReplanService(
            repository=self.plan_repository,
            plan_builder=self.plan_builder,
            clock=clock,
            catalog_provider=self.capability_registry.routing_catalog,
        )
        self.recovery = recovery or PlanRecovery(clock=clock)
        self.routing_policy = RoutingPolicy(
            capabilities=self.capability_registry,
        )
        # ``build`` supplies the role-bound real/fake adapter.  The direct
        # constructor keeps a deterministic fake for older tests and embedded
        # callers that construct the application without the composition root.
        self.planner = planner if planner is not None else FakePlanner()
        self.synthesis = synthesis if synthesis is not None else FakeSynthesis()
        # ``synthesis`` remains the V3 compatibility injection.  New callers
        # should provide the independently role-bound response composer.
        self.response_composer = response_composer
        self.response_pipeline = (
            ResponseCompositionService(
                composer=response_composer,
                max_output_tokens=config.response_composer_role.max_output_tokens,
                timeout_seconds=config.response_composer_role.timeout_seconds,
                profile=config.response_composer_role.profile_name,
                model_version=config.response_composer_role.model_id,
            )
            if response_composer is not None
            else None
        )
        self.plan_interpreter = PlanInterpreter(
            planner=self.planner,
            capabilities=self.capability_registry,
            max_output_tokens=config.planner_role.max_output_tokens,
            timeout_seconds=config.planner_role.timeout_seconds,
            routing_policy=self.routing_policy,
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
        self.plan_executor = plan_executor or PlanExecutor(
            repository=self.plan_repository,
            capability_registry=self.capability_registry,
            capability_workflow=self.capability_workflow,
            clock=clock,
            max_workers=config.max_parallel_steps,
            synthesis_port=self.synthesis,
            synthesis_max_output_tokens=config.response_composer_role.max_output_tokens,
            synthesis_timeout_seconds=config.response_composer_role.timeout_seconds,
            response_composer_port=response_composer,
            response_composer_max_output_tokens=config.response_composer_role.max_output_tokens,
            response_composer_timeout_seconds=config.response_composer_role.timeout_seconds,
            response_pipeline=self.response_pipeline,
        )
        self.plan_orchestrator = plan_orchestrator or PlanOrchestrator(
            repository=self.plan_repository,
            executor=self.plan_executor,
            clock=clock,
            replan_service=self.replan_service,
        )
        self.context_builder = ContextBuilder(
            context_window=config.context_window_messages,
            reserved_output_tokens=config.conversation_role.max_output_tokens,
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
            response_pipeline=self.response_pipeline,
        )

    # -- session lifecycle -------------------------------------------------

    def new_session(
        self,
        *,
        persistence_mode: PersistenceMode = PersistenceMode.STORE_WITH_RETENTION,
        cloud_mode: CloudMode = CloudMode.LOCAL_ONLY,  # CloudMode.CLOUD_PERMITTED
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

    def build_and_persist_plan(
        self,
        proposal: ExecutionProposal,
        task_id: str,
        *,
        plan_id: str | None = None,
        revision: int = 0,
        parent_plan_id: str | None = None,
        verification_requested: bool = False,
    ) -> ExecutionPlan:
        """Validate against a fresh catalog, then persist before execution."""
        builder = PlanBuilder(
            self.capability_registry.routing_catalog(),
            self.config.execution_plan_limits(),
            default_timeout_seconds=self.config.tool_timeout_seconds,
            synthesis_timeout_seconds=self.config.response_composer_role.timeout_seconds,
            legacy_synthesis_enabled=self.response_pipeline is None,
        )
        plan = builder.build(
            proposal,
            task_id,
            plan_id=plan_id,
            revision=revision,
            parent_plan_id=parent_plan_id,
            verification_requested=verification_requested,
        )
        self.plan_repository.save_plan(plan, at=self.clock.now())
        return plan

    persist_validated_plan = build_and_persist_plan

    def replan_plan(
        self,
        source_plan: ExecutionPlan | str,
        proposal: ExecutionProposal,
        *,
        request: ReplanRequest | None = None,
        trigger: ReplanTrigger | None = None,
        failed_step_id: str | None = None,
        cancellation_accepted: bool = False,
        authorization_denied: bool = False,
        consent_denied: bool = False,
        hard_limit_reached: bool = False,
        uncertain_external_action: bool = False,
        idempotency_safe: bool = True,
        same_contract: bool = True,
        cancellation: CancellationToken | None = None,
    ) -> ReplanResult:
        """Create one policy-approved revision without dispatching it."""
        if isinstance(source_plan, str):
            loaded = self.plan_repository.get_plan(source_plan)
            if loaded is None:
                raise ConfigInvalidError("execution plan was not found")
            resolved = loaded
        else:
            resolved = source_plan
        return self.replan_service.replan(
            resolved,
            proposal,
            request=request,
            trigger=trigger,
            failed_step_id=failed_step_id,
            cancellation_accepted=cancellation_accepted,
            authorization_denied=authorization_denied,
            consent_denied=consent_denied,
            hard_limit_reached=hard_limit_reached,
            uncertain_external_action=uncertain_external_action,
            idempotency_safe=idempotency_safe,
            same_contract=same_contract,
            cancellation=cancellation,
        )

    def reconcile_plans(self) -> tuple[RecoveryReport, ...]:
        """Reconcile persisted nonterminal plans without starting providers."""
        return self.recovery.reconcile_startup(self.plan_repository)

    def execute_plan(
        self,
        plan: ExecutionPlan | str,
        *,
        request: TaskRequest,
        context_text: str,
        context_manifest: ContextManifest,
        cancellation: CancellationToken | None = None,
        request_guardrails: GuardrailController | None = None,
    ) -> PlanExecutionResult:
        """Execute a persisted V3 plan through the independent scheduler."""
        effective_guardrails = request_guardrails
        if effective_guardrails is None and self.guardrails is not None:
            effective_guardrails = self.guardrails.for_request()
        return self.plan_orchestrator.execute(
            plan,
            request=request,
            context_text=context_text,
            context_manifest=context_manifest,
            cancellation=cancellation,
            request_guardrails=effective_guardrails,
        )

    def cancel_plan(self, plan_id: str) -> bool:
        """Request cancellation of one active V3 plan."""
        return self.plan_orchestrator.cancel(plan_id)

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
            else self.synthesis.health()
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

    def _authorization_resume_target(self, request: TaskRequest) -> tuple[str, str] | None:
        authorization_id = request.approval_id or request.action_confirmation_id
        if authorization_id is None:
            return None
        with self._v3_authorization_lock:
            return self._v3_authorization_steps.get(authorization_id)

    def _handle_planned(self, request: TaskRequest) -> ConversationOutcome:
        """Run the V3 planner-to-DAG workflow behind the shared submission API."""
        task_id = f"task-{request.request_id}"
        resume_target = self._authorization_resume_target(request)
        if resume_target is not None:
            plan_id, step_id = resume_target
            plan = self.plan_orchestrator.resume_authorized_step(plan_id, step_id)
            with self._v3_authorization_lock:
                context_text, context_manifest = self._v3_execution_context[plan_id]
        else:
            history = self.repository.recent_messages(
                request.session_id, self.config.context_window_messages
            )
            conversation_context = resolve_conversation_context(
                current_text=request.text,
                history=history,
            )
            prompt, context_manifest = self.context_builder.build(
                current_text=request.text,
                history=history,
            )
            decision = self.plan_interpreter.interpret(
                RouteRequest(
                    request_id=request.request_id,
                    text=request.text,
                    contextual_text=conversation_context.routing_text,
                    cloud_mode=request.cloud_mode,
                ),
                approved_context=prompt,
            )
            if decision.proposal.disposition is not ProposalDisposition.CAPABILITY_PLAN:
                return self.orchestrator.handle(
                    request,
                    route_decision=decision.route_decision,
                )
            try:
                plan = self.build_and_persist_plan(decision.proposal, task_id)
            except PlanValidationError:
                # The builder is intentionally stricter than the advisory
                # planner validator. A fresh-catalog race or stricter DAG rule
                # falls back to the already validated deterministic route.
                return self.orchestrator.handle(
                    request,
                    route_decision=decision.route_decision,
                )
            context_text = conversation_context.remote_text
            task_created = self.repository.start_task(task_id, request.session_id, self.clock.now())
            if task_created:
                self.repository.append_message(
                    request.session_id,
                    Message("user", request.text, self.clock.now()),
                )
            self.plan_repository.append_plan_event(
                plan.plan_id,
                "plan.interpreted",
                decision.proposal.reason_code,
                (
                    f"catalog={decision.catalog_version} "
                    f"fallback={str(decision.fallback_used).lower()}"
                ),
                at=self.clock.now(),
            )
            with self._v3_authorization_lock:
                self._v3_execution_context[plan.plan_id] = (
                    context_text,
                    context_manifest,
                )

        execution = self.execute_plan(
            plan,
            request=request,
            context_text=context_text,
            context_manifest=context_manifest,
        )
        final_result = execution.final_result
        if final_result is None:
            raise ConfigInvalidError("plan execution returned no final result")
        assistant_message: Message | None = None
        if (
            final_result.answer_retained
            and final_result.answer
            and final_result.task_status.value not in {"awaiting_consent", "awaiting_confirmation"}
        ):
            assistant_message = Message("assistant", final_result.answer, self.clock.now())
            self.repository.append_message(request.session_id, assistant_message)

        with self._v3_authorization_lock:
            if execution.consent_proposal is not None:
                consent_proposal = execution.consent_proposal
                self._v3_authorization_steps[consent_proposal.proposal_id] = (
                    consent_proposal.plan_id,
                    consent_proposal.step_id,
                )
            if execution.action_confirmation is not None:
                action_confirmation = execution.action_confirmation
                self._v3_authorization_steps[action_confirmation.confirmation_id] = (
                    action_confirmation.plan_id,
                    action_confirmation.step_id,
                )
            if execution.consent_proposal is None and execution.action_confirmation is None:
                self._v3_execution_context.pop(plan.plan_id, None)
                authorization_id = request.approval_id or request.action_confirmation_id
                if authorization_id is not None:
                    self._v3_authorization_steps.pop(authorization_id, None)
        return ConversationOutcome(
            result=final_result,
            manifest=context_manifest,
            assistant_message=assistant_message,
            consent_proposal=execution.consent_proposal,
            action_confirmation=execution.action_confirmation,
        )

    def submit(self, request: TaskRequest) -> Future[ConversationOutcome]:
        """Submit a conversation through bounded local admission."""
        if self.executor is None:
            raise RuntimeError("task executor is not configured")
        handler = self._handle_planned if self._planning_enabled else self.orchestrator.handle
        return self.executor.submit(lambda: handler(request))


def build(toml_path: str | None = None) -> Application:
    """Build the fully-wired M6 application.

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
        synthesis=(
            FakeSynthesis()
            if config.response_composer_role.provider == "fake"
            else OllamaSynthesis(role=config.response_composer_role)
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

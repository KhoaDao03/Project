"""Plan, step-result, event, and synthesis persistence implementation."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone

from elly.application.plan_state import ensure_plan_transition, ensure_step_transition
from elly.application.step_results import StepResultEnvelope
from elly.domain.enums import ActionCategory, PersistenceMode
from elly.domain.errors import (
    ConflictError,
    InputInvalidError,
    MalformedResultError,
    StorageFailureError,
)
from elly.domain.models import TaskResult
from elly.planning.contracts import (
    AuthorizationState,
    ExecutionPlan,
    FinalizationStrategy,
    InputBinding,
    PlanLimitsSnapshot,
    PlanStatus,
    PlanStep,
    StepCriticality,
    StepKind,
    StepState,
)
from elly.ports.plan_repository import PlanEvent, SynthesisResultRecord
from elly.trace_safety import redact_trace_detail

from .codecs import _iso, _parse, _task_result_from_payload, _task_result_payload
from .connection import _SerializedConnection
from .schema import _SAFE_EVENT_CODE


class _PlanStore:
    """Internal plan persistence surface mixed into the public façade."""

    _conn: _SerializedConnection

    def save_plan(self, plan: ExecutionPlan, *, at: datetime | None = None) -> None:
        """Insert one complete validated plan in a single SQLite transaction."""
        if not isinstance(plan, ExecutionPlan):
            raise StorageFailureError("plan persistence requires an ExecutionPlan")
        recorded_at = at or datetime.now(timezone.utc)
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO execution_plans ("
                    "plan_id,task_id,schema_version,revision,parent_plan_id,catalog_version,"
                    "finalization,status,max_plan_steps,max_specialist_executions,"
                    "max_research_executions,max_synthesis_executions,max_provider_calls,"
                    "max_concurrency,max_replanning_attempts,max_parallel_steps,"
                    "max_step_timeout_seconds,max_total_timeout_seconds,created_at,updated_at"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        plan.plan_id,
                        plan.task_id,
                        plan.schema_version,
                        plan.revision,
                        plan.parent_plan_id,
                        plan.catalog_version,
                        plan.finalization.value,
                        plan.status.value,
                        plan.limits.max_plan_steps,
                        plan.limits.max_specialist_executions,
                        plan.limits.max_research_executions,
                        plan.limits.max_synthesis_executions,
                        plan.limits.max_provider_calls,
                        plan.limits.max_concurrency,
                        plan.limits.max_replanning_attempts,
                        plan.limits.max_parallel_steps,
                        plan.limits.max_step_timeout_seconds,
                        plan.limits.max_total_timeout_seconds,
                        _iso(recorded_at),
                        _iso(recorded_at),
                    ),
                )
                for position, step in enumerate(plan.steps):
                    self._conn.execute(
                        "INSERT INTO plan_steps ("
                        "plan_id,step_id,position,kind,capability_id,operation_id,objective,"
                        "objective_class,perspective,inputs_json,output_type,criticality,"
                        "verification,timeout_seconds,requires_external_access,effect,"
                        "requires_consent,state,authorization_state"
                        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            plan.plan_id,
                            step.step_id,
                            position,
                            step.kind.value,
                            step.capability_id,
                            step.operation_id,
                            step.objective,
                            step.objective_class,
                            step.perspective,
                            json.dumps(
                                [
                                    {
                                        "name": item.name,
                                        "value_type": item.value_type,
                                        "source": item.source,
                                        "reference": item.reference,
                                        "required": item.required,
                                    }
                                    for item in step.inputs
                                ],
                                ensure_ascii=False,
                                separators=(",", ":"),
                                sort_keys=True,
                            ),
                            step.output_type,
                            step.criticality.value,
                            int(step.verification),
                            step.timeout_seconds,
                            int(step.requires_external_access),
                            step.effect.value,
                            int(step.requires_consent),
                            step.state.value,
                            step.authorization_state.value,
                        ),
                    )
                for step in plan.steps:
                    for dependency in step.dependencies:
                        self._conn.execute(
                            "INSERT INTO plan_dependencies(plan_id,step_id,dependency_step_id) "
                            "VALUES (?,?,?)",
                            (plan.plan_id, step.step_id, dependency),
                        )
                self._insert_plan_event(
                    plan.plan_id,
                    "plan.created",
                    "PLAN_VALIDATED",
                    (
                        f"revision={plan.revision} schema={plan.schema_version} "
                        f"catalog={plan.catalog_version} finalization={plan.finalization.value}"
                    ),
                    recorded_at,
                )
        except sqlite3.IntegrityError as exc:
            raise StorageFailureError("plan already exists or has conflicting graph rows") from exc
        except sqlite3.Error as exc:
            raise StorageFailureError(f"save plan failed: {type(exc).__name__}") from exc

    def persist_plan_atomic(self, plan: ExecutionPlan, *, at: datetime | None = None) -> None:
        """Explicit-name alias documenting the all-or-nothing persistence boundary."""
        self.save_plan(plan, at=at)

    def get_plan(self, plan_id: str) -> ExecutionPlan | None:
        try:
            row = self._conn.execute(
                "SELECT plan_id,task_id,schema_version,revision,parent_plan_id,catalog_version,"
                "finalization,status,max_plan_steps,max_specialist_executions,"
                "max_research_executions,max_synthesis_executions,max_provider_calls,"
                "max_concurrency,max_replanning_attempts,max_parallel_steps,"
                "max_step_timeout_seconds,max_total_timeout_seconds "
                "FROM execution_plans WHERE plan_id=?",
                (plan_id,),
            ).fetchone()
            if row is None:
                return None
            step_rows = self._conn.execute(
                "SELECT plan_id,step_id,kind,capability_id,operation_id,objective,"
                "objective_class,perspective,inputs_json,output_type,criticality,"
                "verification,timeout_seconds,requires_external_access,effect,"
                "requires_consent,state,authorization_state "
                "FROM plan_steps WHERE plan_id=? ORDER BY position",
                (plan_id,),
            ).fetchall()
            dependency_rows = self._conn.execute(
                "SELECT step_id,dependency_step_id FROM plan_dependencies "
                "WHERE plan_id=? ORDER BY step_id,dependency_step_id",
                (plan_id,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageFailureError(f"get plan failed: {type(exc).__name__}") from exc

        dependencies: dict[str, list[str]] = {}
        for step_id, dependency in dependency_rows:
            dependencies.setdefault(step_id, []).append(dependency)
        try:
            steps = tuple(
                PlanStep(
                    step_id=step_row[1],
                    kind=StepKind(step_row[2]),
                    capability_id=step_row[3],
                    operation_id=step_row[4],
                    objective=step_row[5],
                    objective_class=step_row[6],
                    perspective=step_row[7],
                    inputs=tuple(
                        InputBinding(
                            name=item["name"],
                            value_type=item["value_type"],
                            source=item.get("source", "request"),
                            reference=item.get("reference", ""),
                            required=bool(item.get("required", True)),
                        )
                        for item in json.loads(step_row[8])
                    ),
                    dependencies=tuple(dependencies.get(step_row[1], ())),
                    output_type=step_row[9],
                    criticality=StepCriticality(step_row[10]),
                    verification=bool(step_row[11]),
                    timeout_seconds=float(step_row[12]),
                    requires_external_access=bool(step_row[13]),
                    effect=ActionCategory(step_row[14]),
                    requires_consent=bool(step_row[15]),
                    state=StepState(step_row[16]),
                    authorization_state=AuthorizationState(step_row[17]),
                )
                for step_row in step_rows
            )
            limits = PlanLimitsSnapshot(
                max_plan_steps=int(row[8]),
                max_specialist_executions=int(row[9]),
                max_research_executions=int(row[10]),
                max_synthesis_executions=int(row[11]),
                max_provider_calls=int(row[12]),
                max_concurrency=int(row[13]),
                max_replanning_attempts=int(row[14]),
                max_parallel_steps=int(row[15]),
                max_step_timeout_seconds=float(row[16]),
                max_total_timeout_seconds=float(row[17]),
            )
            return ExecutionPlan(
                plan_id=row[0],
                task_id=row[1],
                schema_version=row[2],
                revision=int(row[3]),
                parent_plan_id=row[4],
                steps=steps,
                finalization=FinalizationStrategy(row[6]),
                limits=limits,
                catalog_version=row[5],
                status=PlanStatus(row[7]),
            )
        except (InputInvalidError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise StorageFailureError("stored execution plan is invalid") from exc

    def list_plans_for_task(self, task_id: str) -> tuple[ExecutionPlan, ...]:
        try:
            rows = self._conn.execute(
                "SELECT plan_id FROM execution_plans WHERE task_id=? ORDER BY revision,plan_id",
                (task_id,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageFailureError(f"list plans failed: {type(exc).__name__}") from exc
        plans: list[ExecutionPlan] = []
        for (plan_id,) in rows:
            plan = self.get_plan(plan_id)
            if plan is None:
                raise StorageFailureError("plan disappeared while listing revisions")
            plans.append(plan)
        return tuple(plans)

    def list_nonterminal_plans(self) -> tuple[ExecutionPlan, ...]:
        """Return plans that may have been left active by a process restart."""
        try:
            rows = self._conn.execute(
                "SELECT plan_id FROM execution_plans "
                "WHERE status IN (?,?) ORDER BY task_id,revision,plan_id",
                (PlanStatus.PENDING.value, PlanStatus.RUNNING.value),
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageFailureError(
                f"list nonterminal plans failed: {type(exc).__name__}"
            ) from exc
        plans: list[ExecutionPlan] = []
        for (plan_id,) in rows:
            plan = self.get_plan(plan_id)
            if plan is None:
                raise StorageFailureError("nonterminal plan disappeared while listing")
            plans.append(plan)
        return tuple(plans)

    def delete_plans_for_task(self, task_id: str) -> int:
        try:
            with self._conn:
                cursor = self._conn.execute(
                    "DELETE FROM execution_plans WHERE task_id=?", (task_id,)
                )
                return cursor.rowcount
        except sqlite3.Error as exc:
            raise StorageFailureError(f"delete plans failed: {type(exc).__name__}") from exc

    def transition_plan(
        self,
        plan_id: str,
        status: PlanStatus,
        *,
        expected_status: PlanStatus | None = None,
        reason_code: str = "",
        at: datetime | None = None,
    ) -> ExecutionPlan:
        """Compare-and-set a plan status and record the safe transition."""
        if not isinstance(status, PlanStatus):
            raise StorageFailureError("plan status transition is invalid")
        recorded_at = at or datetime.now(timezone.utc)
        try:
            with self._conn:
                row = self._conn.execute(
                    "SELECT status FROM execution_plans WHERE plan_id=?", (plan_id,)
                ).fetchone()
                if row is None:
                    raise StorageFailureError("plan not found")
                current = PlanStatus(row[0])
                if expected_status is not None and current is not expected_status:
                    raise ConflictError("plan status changed before transition")
                ensure_plan_transition(current, status)
                self._conn.execute(
                    "UPDATE execution_plans SET status=?,updated_at=? WHERE plan_id=?",
                    (status.value, _iso(recorded_at), plan_id),
                )
                self._insert_plan_event(
                    plan_id,
                    "plan.transition",
                    reason_code or status.value.upper(),
                    f"status={status.value}",
                    recorded_at,
                )
        except (ConflictError, StorageFailureError):
            raise
        except (sqlite3.Error, ValueError) as exc:
            raise StorageFailureError(f"plan transition failed: {type(exc).__name__}") from exc
        updated = self.get_plan(plan_id)
        if updated is None:  # pragma: no cover - guarded by the transaction above
            raise StorageFailureError("plan disappeared after transition")
        return updated

    def transition_step(
        self,
        plan_id: str,
        step_id: str,
        state: StepState,
        *,
        expected_state: StepState | None = None,
        authorization_state: AuthorizationState | None = None,
        reason_code: str = "",
        at: datetime | None = None,
    ) -> ExecutionPlan:
        """Compare-and-set one step state in the same transaction as its event."""
        if not isinstance(state, StepState):
            raise StorageFailureError("plan step state transition is invalid")
        if authorization_state is not None and not isinstance(
            authorization_state, AuthorizationState
        ):
            raise StorageFailureError("plan step authorization state is invalid")
        recorded_at = at or datetime.now(timezone.utc)
        try:
            with self._conn:
                row = self._conn.execute(
                    "SELECT state,authorization_state FROM plan_steps "
                    "WHERE plan_id=? AND step_id=?",
                    (plan_id, step_id),
                ).fetchone()
                if row is None:
                    raise StorageFailureError("plan step not found")
                current = StepState(row[0])
                if expected_state is not None and current is not expected_state:
                    raise ConflictError("plan step state changed before transition")
                ensure_step_transition(current, state)
                auth_value = (
                    authorization_state.value if authorization_state is not None else row[1]
                )
                self._conn.execute(
                    "UPDATE plan_steps SET state=?,authorization_state=? "
                    "WHERE plan_id=? AND step_id=?",
                    (state.value, auth_value, plan_id, step_id),
                )
                self._conn.execute(
                    "UPDATE execution_plans SET updated_at=? WHERE plan_id=?",
                    (_iso(recorded_at), plan_id),
                )
                self._insert_plan_event(
                    plan_id,
                    "step.transition",
                    reason_code or state.value.upper(),
                    f"step={step_id} state={state.value}",
                    recorded_at,
                )
        except (ConflictError, StorageFailureError):
            raise
        except (sqlite3.Error, ValueError) as exc:
            raise StorageFailureError(f"step transition failed: {type(exc).__name__}") from exc
        updated = self.get_plan(plan_id)
        if updated is None:  # pragma: no cover - guarded by the transaction above
            raise StorageFailureError("plan disappeared after step transition")
        return updated

    def reconcile_plan(
        self,
        plan_id: str,
        status: PlanStatus,
        *,
        expected_status: PlanStatus | None = None,
        reason_code: str = "",
        at: datetime | None = None,
    ) -> ExecutionPlan:
        """Reset a pending/running plan during startup reconciliation.

        Normal lifecycle transitions intentionally do not permit RUNNING back
        to PENDING. Recovery is a separate, explicit operation so a restart
        cannot accidentally become a general-purpose status mutation.
        """
        if status not in {PlanStatus.PENDING, PlanStatus.INTERRUPTED}:
            raise StorageFailureError("recovery plan status is invalid")
        recorded_at = at or datetime.now(timezone.utc)
        try:
            with self._conn:
                row = self._conn.execute(
                    "SELECT status FROM execution_plans WHERE plan_id=?", (plan_id,)
                ).fetchone()
                if row is None:
                    raise StorageFailureError("plan not found")
                current = PlanStatus(row[0])
                if expected_status is not None and current is not expected_status:
                    raise ConflictError("plan status changed before recovery")
                if current not in {PlanStatus.PENDING, PlanStatus.RUNNING}:
                    raise ConflictError("plan is no longer recoverable")
                self._conn.execute(
                    "UPDATE execution_plans SET status=?,updated_at=? WHERE plan_id=?",
                    (status.value, _iso(recorded_at), plan_id),
                )
                self._insert_plan_event(
                    plan_id,
                    "recovery.plan",
                    reason_code or "PLAN_RECOVERED",
                    f"from={current.value} status={status.value}",
                    recorded_at,
                )
        except (ConflictError, StorageFailureError):
            raise
        except (sqlite3.Error, ValueError) as exc:
            raise StorageFailureError(f"plan recovery failed: {type(exc).__name__}") from exc
        updated = self.get_plan(plan_id)
        if updated is None:  # pragma: no cover - guarded by the transaction above
            raise StorageFailureError("plan disappeared after recovery")
        return updated

    def reconcile_step(
        self,
        plan_id: str,
        step_id: str,
        state: StepState,
        *,
        expected_state: StepState | None = None,
        reason_code: str = "",
        at: datetime | None = None,
    ) -> ExecutionPlan:
        """Reset a crash-interrupted step without invoking a provider."""
        if state not in {StepState.PENDING, StepState.INTERRUPTED}:
            raise StorageFailureError("recovery step state is invalid")
        recorded_at = at or datetime.now(timezone.utc)
        try:
            with self._conn:
                row = self._conn.execute(
                    "SELECT state FROM plan_steps WHERE plan_id=? AND step_id=?",
                    (plan_id, step_id),
                ).fetchone()
                if row is None:
                    raise StorageFailureError("plan step not found")
                current = StepState(row[0])
                if expected_state is not None and current is not expected_state:
                    raise ConflictError("plan step state changed before recovery")
                if current not in {
                    StepState.AUTHORIZING,
                    StepState.RUNNING,
                    StepState.INTERRUPTED,
                }:
                    raise ConflictError("plan step is no longer recoverable")
                self._conn.execute(
                    "UPDATE plan_steps SET state=? WHERE plan_id=? AND step_id=?",
                    (state.value, plan_id, step_id),
                )
                self._conn.execute(
                    "UPDATE execution_plans SET updated_at=? WHERE plan_id=?",
                    (_iso(recorded_at), plan_id),
                )
                self._insert_plan_event(
                    plan_id,
                    "recovery.step",
                    reason_code or "STEP_RECOVERED",
                    f"step={step_id} from={current.value} state={state.value}",
                    recorded_at,
                )
        except (ConflictError, StorageFailureError):
            raise
        except (sqlite3.Error, ValueError) as exc:
            raise StorageFailureError(f"step recovery failed: {type(exc).__name__}") from exc
        updated = self.get_plan(plan_id)
        if updated is None:  # pragma: no cover - guarded by the transaction above
            raise StorageFailureError("plan disappeared after step recovery")
        return updated

    def save_step_result(
        self,
        plan_id: str,
        step_id: str,
        result: TaskResult,
        *,
        retained: bool = True,
        at: datetime | None = None,
    ) -> None:
        """Persist a normalized result without making it a task-level result."""
        if not isinstance(result, TaskResult):
            raise StorageFailureError("step result must be a TaskResult")
        if not isinstance(retained, bool):
            raise StorageFailureError("step result retained flag is invalid")
        recorded_at = at or datetime.now(timezone.utc)
        try:
            plan_row = self._conn.execute(
                "SELECT task_id FROM execution_plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
            if plan_row is None:
                raise StorageFailureError("plan not found")
            if result.task_id != plan_row[0]:
                raise StorageFailureError("step result task identity does not match plan")
            step_row = self._conn.execute(
                "SELECT 1 FROM plan_steps WHERE plan_id=? AND step_id=?",
                (plan_id, step_id),
            ).fetchone()
            if step_row is None:
                raise StorageFailureError("plan step not found")
            session_row = self._conn.execute(
                "SELECT persistence_mode FROM sessions WHERE session_id=("
                "SELECT session_id FROM tasks WHERE task_id=?)",
                (result.task_id,),
            ).fetchone()
            session_retains = (
                session_row is None or session_row[0] == PersistenceMode.STORE_WITH_RETENTION.value
            )
            answer_retained = bool(retained and result.answer_retained and session_retains)
            payload = _task_result_payload(
                result,
                answer=result.answer if answer_retained else "",
                answer_retained=answer_retained,
                claims=result.claims if answer_retained else (),
                partial_work=result.partial_work if answer_retained else (),
            )
            result_id = f"result-{step_id}"
            with self._conn:
                self._conn.execute(
                    "INSERT OR REPLACE INTO step_results "
                    "(plan_id,step_id,result_id,status,result_json,retained,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        plan_id,
                        step_id,
                        result_id,
                        result.task_status.value,
                        json.dumps(
                            payload,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        int(answer_retained),
                        _iso(recorded_at),
                        _iso(recorded_at),
                    ),
                )
                self._insert_plan_event(
                    plan_id,
                    "step.result",
                    "STEP_RESULT_RETAINED" if answer_retained else "STEP_RESULT_METADATA_ONLY",
                    f"step={step_id} result_id={result_id} status={result.task_status.value}",
                    recorded_at,
                )
        except StorageFailureError:
            raise
        except (sqlite3.Error, TypeError, ValueError) as exc:
            raise StorageFailureError(f"save step result failed: {type(exc).__name__}") from exc

    def get_step_result(self, plan_id: str, step_id: str) -> TaskResult | None:
        try:
            row = self._conn.execute(
                "SELECT result_json FROM step_results WHERE plan_id=? AND step_id=?",
                (plan_id, step_id),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageFailureError(f"get step result failed: {type(exc).__name__}") from exc
        if row is None:
            return None
        try:
            payload = json.loads(row[0])
            if isinstance(payload, dict) and "schema_version" in payload:
                return StepResultEnvelope.from_dict(payload).to_task_result()
            return _task_result_from_payload(payload)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError, MalformedResultError) as exc:
            raise StorageFailureError("stored step result is invalid") from exc

    def save_step_envelope(
        self,
        plan_id: str,
        step_id: str,
        envelope: StepResultEnvelope,
        *,
        retained: bool = True,
        at: datetime | None = None,
    ) -> None:
        """Persist a versioned result without creating a task-level completion."""
        if not isinstance(envelope, StepResultEnvelope):
            raise StorageFailureError("step result envelope has an invalid type")
        if not isinstance(retained, bool):
            raise StorageFailureError("step result retained flag is invalid")
        recorded_at = at or datetime.now(timezone.utc)
        try:
            plan_row = self._conn.execute(
                "SELECT task_id FROM execution_plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
            if plan_row is None:
                raise StorageFailureError("plan not found")
            if envelope.plan_id != plan_id or envelope.task_id != plan_row[0]:
                raise StorageFailureError("step result envelope identity does not match plan")
            step_row = self._conn.execute(
                "SELECT 1 FROM plan_steps WHERE plan_id=? AND step_id=?",
                (plan_id, step_id),
            ).fetchone()
            if step_row is None or envelope.step_id != step_id:
                raise StorageFailureError("plan step not found")
            session_row = self._conn.execute(
                "SELECT persistence_mode FROM sessions WHERE session_id=("
                "SELECT session_id FROM tasks WHERE task_id=?)",
                (envelope.task_id,),
            ).fetchone()
            session_retains = (
                session_row is None or session_row[0] == PersistenceMode.STORE_WITH_RETENTION.value
            )
            answer_retained = bool(retained and envelope.answer_retained and session_retains)
            persisted = envelope
            if not answer_retained:
                persisted = replace(
                    envelope,
                    summary="",
                    answer="",
                    findings=(),
                    claims=(),
                    claim_supports=(),
                    assumptions=(),
                    uncertainties=(),
                    warnings=(),
                    structured_output={},
                    answer_retained=False,
                )
            payload = persisted.to_dict()
            with self._conn:
                self._conn.execute(
                    "INSERT OR REPLACE INTO step_results "
                    "(plan_id,step_id,result_id,status,result_json,retained,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        plan_id,
                        step_id,
                        f"result-{step_id}",
                        persisted.status.value,
                        json.dumps(
                            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                        ),
                        int(answer_retained),
                        _iso(recorded_at),
                        _iso(recorded_at),
                    ),
                )
                self._insert_plan_event(
                    plan_id,
                    "step.result",
                    "STEP_RESULT_RETAINED" if answer_retained else "STEP_RESULT_METADATA_ONLY",
                    f"step={step_id} result_id=result-{step_id} status={persisted.status.value}",
                    recorded_at,
                )
        except StorageFailureError:
            raise
        except (sqlite3.Error, TypeError, ValueError, MalformedResultError) as exc:
            raise StorageFailureError(
                f"save step result envelope failed: {type(exc).__name__}"
            ) from exc

    def get_step_envelope(self, plan_id: str, step_id: str) -> StepResultEnvelope | None:
        try:
            row = self._conn.execute(
                "SELECT result_json FROM step_results WHERE plan_id=? AND step_id=?",
                (plan_id, step_id),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageFailureError(
                f"get step result envelope failed: {type(exc).__name__}"
            ) from exc
        if row is None:
            return None
        try:
            payload = json.loads(row[0])
            if not isinstance(payload, dict) or "schema_version" not in payload:
                return None
            return StepResultEnvelope.from_dict(payload)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError, MalformedResultError) as exc:
            raise StorageFailureError("stored step result envelope is invalid") from exc

    def append_plan_event(
        self,
        plan_id: str,
        event_type: str,
        reason_code: str,
        detail: str = "",
        *,
        at: datetime | None = None,
    ) -> None:
        recorded_at = at or datetime.now(timezone.utc)
        try:
            with self._conn:
                self._insert_plan_event(plan_id, event_type, reason_code, detail, recorded_at)
        except sqlite3.Error as exc:
            raise StorageFailureError(f"append plan event failed: {type(exc).__name__}") from exc

    def _insert_plan_event(
        self,
        plan_id: str,
        event_type: str,
        reason_code: str,
        detail: str,
        at: datetime,
    ) -> None:
        if (
            not isinstance(event_type, str)
            or not isinstance(reason_code, str)
            or _SAFE_EVENT_CODE.fullmatch(event_type) is None
            or _SAFE_EVENT_CODE.fullmatch(reason_code) is None
        ):
            raise StorageFailureError("plan event codes are invalid")
        safe_detail = redact_trace_detail(detail)
        if len(safe_detail) > 256 or "\n" in safe_detail or "\r" in safe_detail:
            raise StorageFailureError("plan event detail exceeds its safe bound")
        self._conn.execute(
            "INSERT INTO plan_events(plan_id,event_type,reason_code,detail,created_at) "
            "VALUES (?,?,?,?,?)",
            (plan_id, event_type, reason_code, safe_detail, _iso(at)),
        )

    def plan_events(self, plan_id: str) -> tuple[PlanEvent, ...]:
        try:
            rows = self._conn.execute(
                "SELECT plan_id,event_type,reason_code,detail,created_at "
                "FROM plan_events WHERE plan_id=? ORDER BY event_id",
                (plan_id,),
            ).fetchall()
            return tuple(
                PlanEvent(
                    plan_id=row[0],
                    event_type=row[1],
                    reason_code=row[2],
                    detail=row[3],
                    created_at=_parse(row[4]),
                )
                for row in rows
            )
        except sqlite3.Error as exc:
            raise StorageFailureError(f"query plan events failed: {type(exc).__name__}") from exc

    def save_synthesis_result(
        self,
        plan_id: str,
        strategy: FinalizationStrategy,
        validation_state: str,
        referenced_result_ids: tuple[str, ...],
        output: Mapping[str, object],
        *,
        at: datetime | None = None,
    ) -> None:
        recorded_at = at or datetime.now(timezone.utc)
        if not isinstance(strategy, FinalizationStrategy):
            raise StorageFailureError("synthesis strategy is invalid")
        if (
            not isinstance(validation_state, str)
            or not validation_state.strip()
            or len(validation_state) > 128
            or "\n" in validation_state
            or "\r" in validation_state
        ):
            raise StorageFailureError("synthesis validation state is invalid")
        if not isinstance(referenced_result_ids, tuple) or any(
            not isinstance(item, str) or not item.strip() for item in referenced_result_ids
        ):
            raise StorageFailureError("synthesis result references are invalid")
        if not isinstance(output, Mapping):
            raise StorageFailureError("synthesis output is invalid")
        try:
            output_json = json.dumps(
                dict(output),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                allow_nan=False,
            )
            if len(output_json.encode("utf-8")) > 32_768:
                raise StorageFailureError("synthesis output exceeds its size limit")
            validation_event_code = re.sub(r"[^A-Za-z0-9_.-]", "_", validation_state.strip())[:64]
            if not validation_event_code or not validation_event_code[0].isalpha():
                validation_event_code = "SYNTHESIS_" + validation_event_code[:54]
            with self._conn:
                self._conn.execute(
                    "INSERT INTO synthesis_results "
                    "(plan_id,strategy,validation_state,referenced_result_ids_json,output_json,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?) "
                    "ON CONFLICT(plan_id) DO UPDATE SET strategy=excluded.strategy, "
                    "validation_state=excluded.validation_state, "
                    "referenced_result_ids_json=excluded.referenced_result_ids_json, "
                    "output_json=excluded.output_json, updated_at=excluded.updated_at",
                    (
                        plan_id,
                        strategy.value,
                        validation_state.strip(),
                        json.dumps(list(referenced_result_ids), separators=(",", ":")),
                        output_json,
                        _iso(recorded_at),
                        _iso(recorded_at),
                    ),
                )
                self._insert_plan_event(
                    plan_id,
                    (
                        "response_composer.result"
                        if validation_state.startswith("response_composition:")
                        else "synthesis.result"
                    ),
                    validation_event_code,
                    (
                        f"strategy={strategy.value} refs={len(referenced_result_ids)} "
                        f"result_id=synthesis-{plan_id}"
                    ),
                    recorded_at,
                )
        except StorageFailureError:
            raise
        except (sqlite3.Error, TypeError, ValueError) as exc:
            raise StorageFailureError(
                f"save synthesis result failed: {type(exc).__name__}"
            ) from exc

    def get_synthesis_result(self, plan_id: str) -> SynthesisResultRecord | None:
        try:
            row = self._conn.execute(
                "SELECT plan_id,strategy,validation_state,referenced_result_ids_json,"
                "output_json,created_at,updated_at FROM synthesis_results WHERE plan_id=?",
                (plan_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageFailureError(f"get synthesis result failed: {type(exc).__name__}") from exc
        if row is None:
            return None
        try:
            references = json.loads(row[3])
            output = json.loads(row[4])
            if not isinstance(references, list) or not isinstance(output, dict):
                raise ValueError
            return SynthesisResultRecord(
                plan_id=row[0],
                strategy=FinalizationStrategy(row[1]),
                validation_state=row[2],
                referenced_result_ids=tuple(references),
                output=output,
                created_at=_parse(row[5]),
                updated_at=_parse(row[6]),
            )
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise StorageFailureError("stored synthesis result is invalid") from exc

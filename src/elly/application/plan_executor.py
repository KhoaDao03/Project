"""Compatibility exports for the decomposed task-execution implementation.

New code should depend on :mod:`elly.application.task_execution`.  This
module intentionally contains no execution state or scheduling logic; it
preserves established import paths and the historical ``PlanExecutor`` and
``PlanRunResult`` names while callers migrate.
"""

from .task_execution import (
    PlanExecutionRequest,
    PlanExecutionResult,
    PlanExecutor,
    PlanFinalizer,
    PlanRunner,
    PlanRunResult,
    PlanStatusPolicy,
    StepRunner,
    TaskExecutionService,
)

__all__ = [
    "PlanFinalizer",
    "PlanExecutionRequest",
    "PlanExecutionResult",
    "PlanExecutor",
    "PlanRunResult",
    "PlanRunner",
    "PlanStatusPolicy",
    "StepRunner",
    "TaskExecutionService",
]

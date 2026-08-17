"""Decomposed task execution components.

The package owns the execution implementation.  ``plan_executor`` remains a
thin compatibility module for established import paths and aliases.
"""

from elly.application.plan_results import PlanStatusPolicy

from .contracts import PlanExecutionRequest, PlanExecutionResult, PlanRunResult
from .finalizer import PlanFinalizer
from .plan_runner import PlanRunner
from .service import TaskExecutionService
from .step_runner import StepRunner

PlanExecutor = TaskExecutionService

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

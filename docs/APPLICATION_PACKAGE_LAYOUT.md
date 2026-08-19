# Application package layout

This is a Level 1 physical package-organization note. It does not introduce a
new architecture phase, service, contract, or runtime behavior. The architecture
consolidation remains closed; the tree below only groups existing application
modules by responsibility.

```text
src/elly/application/
├── runtime.py                 outer request/task lifecycle
├── completion.py              final task completion and persistence
├── context_builder.py         bounded request context
├── authorization/
│   ├── consent.py             hosted/cloud consent authorization
│   └── actions.py             consequential-action authorization
├── routing/
│   ├── policy.py              routing policy
│   ├── catalog.py             catalog interpretation and selection
│   ├── contracts.py           routing contracts and descriptors
│   └── compatibility.py       historical route translation/metadata
├── plan_management/
│   ├── service.py             PlanningService
│   ├── builder.py             plan construction and DAG validation
│   ├── interpreter.py         proposal interpretation
│   ├── validation.py          plan validation result
│   ├── redundancy_policy.py   redundancy policy
│   └── specialist_policy.py   specialist execution policy
├── capabilities/
│   ├── registry.py             CapabilityRegistry and descriptors
│   ├── handlers.py             registered capability handlers
│   ├── workflow.py             selected-capability execution workflow
│   ├── local_conversation.py   local conversation use case
│   ├── local_conversation_handler.py
│   ├── research.py             application research pipeline
│   └── specialists.py          application specialist workflow
├── results/
│   ├── plan.py                 plan aggregation and finalization data
│   ├── step.py                 typed step result envelopes
│   └── plan_state.py           plan/step transition rules
├── response/
│   ├── composer.py             deterministic result composition helpers
│   ├── pipeline.py             response-composition service
│   └── policy.py               presentation-mode policy
└── task_execution/
    ├── contracts.py            execution request/result contracts
    ├── service.py              TaskExecutionService
    ├── plan_runner.py          plan scheduling
    ├── step_runner.py          step dispatch and persistence
    ├── finalizer.py            aggregation/composition handoff
    ├── cancellation.py         request-scoped cancellation
    ├── recovery.py             persisted-plan recovery
    ├── replan.py               bounded replanning
    └── legacy.py               persisted LOCAL_SYNTHESIS compatibility
```

The lower-level `src/elly/planning/` package remains separate for planning
contracts, catalog representation, and codecs. The application package uses
direct submodule imports such as:

```python
from elly.application.capabilities.registry import CapabilityRegistry
from elly.application.plan_management.service import PlanningService
from elly.application.response.pipeline import ResponseCompositionService
from elly.application.routing.policy import RoutingPolicy
from elly.application.task_execution.service import TaskExecutionService
```

The new package initializers are intentionally small; no broad compatibility
barrel for the retired flat module paths is retained.

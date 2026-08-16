# Elly V3 Phase 1 — Independent Local-Model Roles

**Date:** 2026-08-15  
**Baseline:** Closed V2.5 registry-driven routing  
**Status:** Implemented and verified; subsequent planner and execution phases follow

## 1. Scope delivered

Phase 1 adds the configuration and composition foundation for three independent
local-model roles:

- `conversation` handles ordinary local conversation;
- `planner` is reserved for the Phase 2 local planner; and
- `synthesis` is reserved for the Phase 7 evidence-bounded synthesizer.

Each role resolves to an immutable `LocalModelRoleConfig` backed by a named,
reusable `LocalModelProfile`. Roles may share a profile by default without
sharing role-specific output limits or creating a source-level dependency.

## 2. Configuration contract

The new authoritative TOML shape is:

```toml
[local_models.profiles.qwen_default]
provider = "ollama"
model_id = "qwen3:8b"
base_url = "http://127.0.0.1:11434"
timeout_seconds = 120

[local_models.roles]
conversation = "qwen_default"
planner = "qwen_default"
synthesis = "qwen_default"

[local_models.role_limits]
conversation_max_output_tokens = 512
planner_max_output_tokens = 1200
synthesis_max_output_tokens = 1600
```

Built-in defaults bind all three roles to `qwen_default`. The acceptance
profile defaults are now three provider calls and two concurrency slots; an
explicit lower TOML or environment limit remains authoritative.

Supported environment overrides include:

- `ELLY_LOCAL_CONVERSATION_PROFILE`, `ELLY_LOCAL_PLANNER_PROFILE`, and
  `ELLY_LOCAL_SYNTHESIS_PROFILE`;
- `ELLY_LOCAL_MODELS_<PROFILE>_PROVIDER`, `MODEL_ID`, `BASE_URL`, and
  `TIMEOUT_SECONDS`; and
- the corresponding role-specific `MAX_OUTPUT_TOKENS` variables.

Environment values override TOML values. The additional
`ELLY_LOCAL_MODELS_<ROLE>_PROFILE` and role-limit aliases are accepted for
deployment consistency.

## 3. Compatibility and validation

The existing `[generalist]`, `[providers].generalist`, `[models].generalist`,
and legacy generalist environment keys remain supported during the migration
window. When no V3 local profile or role binding is supplied, they populate one
generated `v2_generalist` profile and bind all roles to it. When old and new
configuration coexist, the V3 catalog wins and one redacted deprecation
warning is emitted per configuration load.

Local profiles fail closed when they have an unsafe identifier, unsupported
provider, missing model identity, invalid timeout, or a non-local endpoint.
Role bindings fail closed for unknown roles, unknown profiles, empty names, and
conflicting environment aliases. Remote research and hosted-specialist
provider/model settings are parsed and resolved independently.

## 4. Runtime integration

The composition root now resolves the conversation adapter exclusively through
the `conversation` role. Its model ID, endpoint, timeout, output ceiling, and
context reservation come from that role. Guardrails reserve the largest output
ceiling across all three local roles and the existing remote capabilities.

The shared status API exposes one non-secret view per role containing its role,
profile name, provider, model ID, endpoint host, timeout, and output ceiling.
The existing V2.5 generalist status fields remain for compatibility, and the
presentation layer adds a compact `Local roles:` line without exposing endpoint
URLs, credentials, query values, or provider responses.

Planner and synthesis provider ports are intentionally not introduced in this
phase; their role configurations are ready for the Phase 2 planner and Phase 7
synthesis implementations.

## 5. Verification

`tests/test_v3_phase1_local_model_roles.py` covers:

- default profile reuse and independent role limits;
- TOML role rebinding and shared-profile behavior;
- environment-over-TOML precedence;
- old-key migration and one-warning conflict handling;
- invalid profiles, endpoints, bindings, and providers;
- remote configuration independence;
- redacted API/presentation status; and
- immutable profile/catalog behavior.

The focused Phase 1, Phase 0, API, interface, and composition tests pass. The
repository-wide gate passes 388 tests, compilation, and whitespace checks; Ruff
and Mypy were not installed in the environment and therefore did not run.

# Specialist manifests

Place declarative `*.toml` manifests here. The M2 registry discovers and validates
them; M5 routes only the declared research and coding roles through the application
workflow. A manifest never grants tool authority: M5 rejects non-empty tool grants
and all high-impact/action requests.

Provider selection, model IDs, and dollar pricing deliberately do not live here.
Configure all of them once in `config.local.toml` under `[providers]`, `[models]`,
and `[pricing]`. `estimated_cost` is only a qualitative routing/risk label.

Invalid manifests are disabled and reported in the registry; they never become
routable. A manifest grants no tool authority by itself.

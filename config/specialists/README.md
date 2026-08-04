# Specialist manifests

Place declarative `*.toml` manifests here. M2 discovers and validates them at
startup, but does not route tasks to or execute specialists. Specialist routing,
provider calls, tool grants, consent, and result contracts are M5 scope.

Invalid manifests are disabled and reported in the registry; they never become
routable. A manifest grants no tool authority by itself.

# M7 Owner UAT Record

Status: owner-reviewed 2026-08-07; four use cases are approved for deferral to later
versions. The remaining UAT scope is approved; deferred use cases are not claimed
as verified for this version.

The following automated evidence demonstrates that the named workflows are
reachable and covered. It is not a substitute for the owner's judgment of
clarity, control, usefulness, or safety.

| Use case | Automated evidence | Owner result |
|---|---|---|
| UC-01 local conversation | `test_composition_and_smoke`, `test_conversation_integration` | In approved current scope |
| UC-02 current research | `test_research`, live hosted-search evidence | In approved current scope |
| UC-03 coding specialist | `test_specialists_m5` | In approved current scope |
| UC-04 privacy/consent | `test_specialists_m5` | **Deferred to a later version** |
| UC-05 evidence/uncertainty | `test_research` | In approved current scope |
| UC-06 startup continuity | `test_m6_data_controls`, `test_sqlite_repository` | **Deferred to a later version** |
| UC-07 cancellation/recovery | `test_guardrails`, `test_orchestrator_conversation` | In approved current scope |
| UC-08 limits/cost | `test_guardrails` | In approved current scope |
| UC-09 profile/session controls | `test_m6_data_controls` | **Deferred to a later version** |
| UC-10 health/status | `test_cli_dispatch`, `test_composition_and_smoke` | In approved current scope |
| UC-11 trace/audit review | `test_m6_data_controls`, `test_audit_redaction` | **Deferred to a later version** |
| UC-12 specialist registry | `test_specialist_registry`, `test_specialists_m5` | In approved current scope |

Owner review fields:

- Clarity: `4 / 5`
- Control/privacy: `3 / 5`
- Usefulness: `4 / 5`
- Safety-critical issue observed: `no`
- Owner decision: `approved`
- Owner/date: `Khoa Dao — 2026-08-07`

Owner verdict: UC-04, UC-06, UC-09, and UC-11 are intentionally deferred and
will be addressed in later versions. The control/privacy score of 3/5 remains a
follow-up signal; no safety-critical issue was observed.

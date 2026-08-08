# M7 Release Checklist — Evaluation, Hardening & UAT

Status: open after independent verification on 2026-08-04. Owner UAT was recorded
on 2026-08-07 with four approved later-version deferrals; the release gate remains
blocked until the remaining aggregate live provider-quality evidence and final
threshold review are complete.

## Evidence command

```bash
PYTHONPATH=src python3 scripts/run_release_gate.py \
  --output tmp/elly-m7-evidence.json --hardware-status pass
```

The command is network-free but now executes the deterministic suite itself. It
freezes all EVAL-001…030 records with model,
provider, prompt version, configuration, fixture version, and timestamp. It maps
deterministic cases to regression evidence and leaves provider-quality, live
research and owner-UAT gates pending rather than fabricating passes. Hardware
defaults to `pending`; use `--hardware-status pass` only when the separate
owner-approved qwen3:8b evidence is in scope.

See [M7_THRESHOLD_REVIEW.md](M7_THRESHOLD_REVIEW.md) for the current gate-by-gate
decision.

## Current gate result

| Gate | Result | Required evidence |
|---|---|---|
| Deterministic safety/schema/limits/contracts | 209/209 pass for implemented scope | Strict full suite; owner-controlled acceptance gaps remain separately blocking |
| EVAL catalog metadata | Pass | 30 pinned records |
| Provider-quality/live research thresholds | Partial evidence | [M7 live evidence](implementStatus/M7_LIVE_EVIDENCE.md); full corpus/rubric pending |
| Hardware threshold | Pass for approved qwen3:8b development profile | [M7 live evidence](implementStatus/M7_LIVE_EVIDENCE.md); owner-approved qwen3:8b fit |
| Owner UAT current scope | Owner-approved with four deferrals | [M7 UAT record](M7_UAT_RECORD.md); UC-04/06/09/11 deferred |

## UAT record

The owner must review the CLI workflows for UC-01…UC-12 using [M7_UAT_RECORD.md](M7_UAT_RECORD.md) and record clarity,
control, usefulness, and any safety issue. A safety-critical failure blocks release
regardless of aggregate score. `qwen3:8b` is the default evaluation model;
`qwen3:14b` is not used unless explicitly requested.

The owner’s final verdict (2026-08-07) records clarity 4/5, control/privacy 3/5,
usefulness 4/5, no safety-critical issue, and approval of the following deferrals:
UC-04, UC-06, UC-09, and UC-11. These capabilities are not represented as verified
in this release and are planned for later versions.

## Deferred by approval

Streaming, web UI, portable trace export, semantic/vector memory, and future
roadmap capabilities remain outside M7.

"""M7 release-evidence runner.

This runner records evidence provenance; it does not turn a fake result into
real-provider verification. Deterministic cases are marked covered only by the
existing named regression suite. Provider-quality, live-research, hardware, and
owner-UAT evidence remain explicitly pending until their required runs occur.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
from typing import Iterable

from .catalog import EvaluationCase, catalog


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    """Pinned evidence status for one catalog case."""
    case_id: str
    status: str
    evidence_class: str
    model_id: str
    provider: str
    prompt_version: str
    configuration: str
    fixture_version: str
    recorded_at: str
    evidence: str


@dataclass(frozen=True, slots=True)
class ReleaseEvidence:
    """Aggregate release gates; only explicit evidence may produce pass states."""
    generated_at: str
    python: str
    platform: str
    regression_command: str
    regression_status: str
    records: tuple[EvaluationRecord, ...]
    deterministic_gate: str
    quality_gate: str
    uat_gate: str
    hardware_gate: str

    @property
    def releasable(self) -> bool:
        return all(gate == "pass" for gate in (self.deterministic_gate, self.quality_gate, self.uat_gate, self.hardware_gate))

    def write_json(self, destination: str) -> None:
        """Serialize the immutable report to a caller-selected local path."""
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        document = asdict(self)
        document["releasable"] = self.releasable
        Path(destination).write_text(json.dumps(document, indent=2) + "\n")


def run_release_evidence(
    *,
    model_id: str = "qwen3:8b",
    provider: str = "ollama",
    prompt_version: str = "m7-baseline-1",
    configuration: str = "config.example.toml",
    fixture_version: str = "eval-catalog-1",
    regression_status: str = "not_run",
    hardware_status: str = "pending",
    recorded_at: datetime | None = None,
    cases: Iterable[EvaluationCase] | None = None,
) -> ReleaseEvidence:
    """Build a pinned release evidence report without making network/model calls."""
    stamp = (recorded_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    records = []
    for case in cases or catalog():
        if case.evidence_class == "deterministic" and regression_status == "pass":
            status, evidence = "covered", case.deterministic_coverage or "regression suite"
        else:
            status, evidence = "pending", f"required evidence class: {case.evidence_class}"
        records.append(EvaluationRecord(
            case_id=case.case_id, status=status, evidence_class=case.evidence_class,
            model_id=model_id, provider=provider, prompt_version=prompt_version,
            configuration=configuration, fixture_version=fixture_version,
            recorded_at=stamp, evidence=evidence,
        ))
    deterministic = "pass" if regression_status == "pass" and all(r.status == "covered" for r in records if r.evidence_class == "deterministic") else "pending"
    quality = "pass" if all(r.status == "pass" for r in records if r.evidence_class in {"provider_quality", "live_research", "live_provider"}) else "pending"
    return ReleaseEvidence(
        generated_at=stamp, python=platform.python_version(), platform=platform.platform(),
        regression_command="PYTHONPATH=src python3 -W error::ResourceWarning -m unittest discover -s tests -t .",
        regression_status=regression_status, records=tuple(records),
        deterministic_gate=deterministic, quality_gate=quality, uat_gate="pending",
        # Hardware evidence is collected separately. Callers must opt in with an
        # explicit evidence-backed status; a report generator cannot infer it.
        hardware_gate=hardware_status,
    )

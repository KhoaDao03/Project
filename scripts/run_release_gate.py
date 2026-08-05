#!/usr/bin/env python3
"""Generate the M7 release-evidence report.

This is intentionally a no-network command. It records deterministic regression
coverage and leaves live quality, hardware, and owner-UAT gates pending.
"""

from argparse import ArgumentParser
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from elly.evaluation import run_release_evidence  # noqa: E402


def main() -> int:
    parser = ArgumentParser()
    parser.add_argument("--output", default="artifacts/m7/release-evidence.json")
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--provider", default="ollama")
    parser.add_argument("--hardware-status", choices=("pending", "pass", "fail"), default="pending")
    args = parser.parse_args()
    regression_command = [
        sys.executable, "-W", "error::ResourceWarning", "-m", "unittest",
        "discover", "-s", "tests", "-t", ".",
    ]
    completed = subprocess.run(regression_command, cwd=Path(__file__).resolve().parents[1], check=False)
    evidence = run_release_evidence(
        model_id=args.model, provider=args.provider,
        regression_status="pass" if completed.returncode == 0 else "fail",
        hardware_status=args.hardware_status,
    )
    evidence.write_json(args.output)
    print(f"Wrote {args.output}")
    print(f"cases={len(evidence.records)} deterministic={evidence.deterministic_gate} quality={evidence.quality_gate} uat={evidence.uat_gate} hardware={evidence.hardware_gate} releasable={evidence.releasable}")
    return 0 if evidence.releasable else 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Collect real-provider M7 evidence without sending owner data.

The workload is deliberately public, bounded, and qwen3:8b-only. The script
records latency/contract observations and application-validated research citation
metadata; it does not assign subjective quality scores or claim owner UAT.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import resource
import subprocess
import threading
from time import monotonic

from elly.adapters.ollama_generalist import OllamaGeneralist
from elly.adapters.openai_web_research import OpenAIHostedWebSearch
from elly.adapters.system_clock import SystemClock
from elly.dotenv import load_dotenv
from elly.domain.models import GeneralistRequest
from elly.ports.web_research import ResearchBudget
from elly.research.citation_validator import validate_citations


PROMPTS = (
    "Explain dependency injection in two concise sentences.",
    "What is a binary search tree? Give three short bullet points.",
    "Explain the difference between a process and a thread without code.",
    "Review this Python expression for a likely bug: len(items) == 0.",
    "Give a concise definition of idempotency in APIs.",
)


class _GpuSampler:
    def __init__(self) -> None:
        self.stop = threading.Event()
        self.samples: list[dict[str, int | str]] = []
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self.stop.is_set():
            try:
                line = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=name,memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
                    text=True, stderr=subprocess.DEVNULL, timeout=2,
                ).strip()
                fields = [field.strip() for field in line.split(",")]
                if len(fields) == 3:
                    self.samples.append({"name": fields[0], "memory_used_mb": int(fields[1]), "utilization_gpu": int(fields[2])})
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
            self.stop.wait(0.1)

    def __enter__(self) -> "_GpuSampler":
        self.thread.start()
        return self

    def __exit__(self, *_args) -> None:
        self.stop.set()
        self.thread.join(timeout=3)


def qwen8_evidence() -> dict:
    adapter = OllamaGeneralist(timeout_seconds=120)
    health = adapter.health()
    samples = []
    started = monotonic()
    with _GpuSampler() as gpu_sampler:
        for prompt in PROMPTS:
            turn_started = monotonic()
            response = adapter.generate(GeneralistRequest(prompt=prompt, model_id="qwen3:8b", max_output_tokens=128))
            latency_ms = int((monotonic() - turn_started) * 1000)
            samples.append({
                "prompt": prompt, "latency_ms": latency_ms,
                "output_tokens": response.usage.output_tokens,
                "tokens_per_second": round(response.usage.output_tokens / max(latency_ms / 1000, 0.001), 2),
                "answer_nonempty": bool(response.text.strip()), "answer": response.text,
            })
    gpu = "unavailable"
    try:
        gpu = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
            text=True, stderr=subprocess.STDOUT, timeout=5,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return {
        "model": "qwen3:8b", "provider": "ollama", "health": health.state.value,
        "samples": samples, "total_latency_ms": int((monotonic() - started) * 1000),
        "maxrss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "gpu_snapshot": gpu, "gpu_samples": gpu_sampler.samples,
        "gpu_peak_memory_used_mb": max((int(item["memory_used_mb"]) for item in gpu_sampler.samples), default=None),
        "gpu_peak_utilization_percent": max((int(item["utilization_gpu"]) for item in gpu_sampler.samples), default=None),
        "platform": platform.platform(),
    }


def research_evidence() -> dict:
    provider = OpenAIHostedWebSearch()
    query = "What is the latest stable Python release? Give the release number and date."
    started = monotonic()
    response = provider.research(query, ResearchBudget(max_results=5, timeout_seconds=60))
    validated = validate_citations(response.citations, now=datetime.now(timezone.utc), resolve_hosts=True)
    return {
        "provider": response.provider, "model": response.model, "query": query,
        "latency_ms": int((monotonic() - started) * 1000),
        "answer_nonempty": bool(response.answer_text.strip()),
        "citation_count": len(response.citations), "validated_citation_count": len(validated.evidence),
        "rejected_citation_count": len(validated.rejected),
        "validated_urls": [item.canonical_url or item.url for item in validated.evidence],
        "answer": response.answer_text,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="tmp/elly-m7-live-evidence.json")
    parser.add_argument("--research", action="store_true")
    args = parser.parse_args()
    load_dotenv()
    report = {"recorded_at": datetime.now(timezone.utc).isoformat(), "qwen8": qwen8_evidence()}
    if args.research:
        report["research"] = research_evidence()
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value if key != "qwen8" else {"health": value["health"], "samples": len(value["samples"]), "model": value["model"]} for key, value in report.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

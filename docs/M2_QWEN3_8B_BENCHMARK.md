# M2 qwen3:8b Benchmark Evidence

**Date:** 2026-08-04  
**Purpose:** M2 development/testing model evidence  
**Model:** `qwen3:8b`  
**Runtime:** Ollama `0.32.5`, localhost API  
**Selection policy:** default development/testing model; `qwen3:14b` is explicit opt-in.

## Live adapter smoke

Command:

```bash
PYTHONPATH=src python3 -c 'from elly.adapters.ollama_generalist import OllamaGeneralist; from elly.domain.models import GeneralistRequest; from time import monotonic; a=OllamaGeneralist(timeout_seconds=30); t=monotonic(); x=a.generate(GeneralistRequest(prompt="Say ok",model_id="qwen3:8b",max_output_tokens=8)); print({"model":"qwen3:8b","latency_ms":int((monotonic()-t)*1000),"output_tokens":x.usage.output_tokens,"answer_nonempty":bool(x.text.strip())})'
```

Observed result:

```text
{'model': 'qwen3:8b', 'latency_ms': 2450, 'output_tokens': 7, 'answer_nonempty': True}
```

The response was returned through `OllamaGeneralist`, not the deterministic fake.
The adapter sent a bounded request and returned non-empty text without exposing
thinking fields.

## Scope and limitations

This is a live smoke measurement, not the final NFR-003 performance gate. It does
not establish sustained throughput, peak VRAM/RAM, crash stability, or a multi-turn
latency distribution. Those measurements require an approved workload and target
thresholds. qwen3:14b remains available only through explicit configuration because
other device workloads can reduce available VRAM.

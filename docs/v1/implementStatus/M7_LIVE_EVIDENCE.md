# M7 Historical Live Evidence Record

> This record was dated 2026-08-05 in a worktree reviewed on 2026-08-04. It is
> retained as prior claimed evidence, not treated as independently contemporaneous
> verification. Current functional results are in `../V1_VERIFICATION_REPORT.md`.

These runs used only public, non-sensitive prompts. `qwen3:14b` was not used.
Raw reports are written to the repository-local ignored `tmp/` directory as
`tmp/elly-m7-qwen8-hardware.json` and `tmp/elly-m7-live-evidence.json`.

## qwen3:8b provider-quality and hardware re-confirmation

Command:

```bash
PYTHONPATH=src python3 scripts/run_m7_live_evidence.py \
  --output tmp/elly-m7-qwen8-hardware.json
```

Observed through the real localhost Ollama adapter:

- Ollama health: healthy.
- Model: `qwen3:8b`.
- Workload: five bounded public prompts, `num_predict=128`, concurrency 1.
- Non-empty responses: 5/5.
- Latencies: 1,931 ms; 2,932 ms; 4,924 ms; 5,676 ms; 2,050 ms.
- Output rates: 17.09, 18.08, 18.68, 14.09, and 18.05 tokens/sec.
- Total workload time: 17,573 ms.
- Peak observed GPU memory: 10,649 MB of 16,376 MB.
- Peak observed GPU utilization: 100%.
- Host GPU: NVIDIA GeForce RTX 4090 Laptop GPU.
- No crash, timeout, empty response, or silent provider fallback occurred.

This is stronger than the prior smoke evidence and re-confirms the owner-approved
qwen3:8b development profile. It does not authorize automatic qwen3:14b use.

## Live hosted research

Command:

```bash
PYTHONPATH=src python3 scripts/run_m7_live_evidence.py --research \
  --output tmp/elly-m7-live-evidence.json
```

Observed with OpenAI hosted `web_search`:

- Provider/model: `openai_web_search` / `gpt-5.6-luna`.
- Query: latest stable Python release, public information only.
- Latency: 6,260 ms.
- Answer: non-empty.
- Provider citations: 2.
- Application-validated citations: 1.
- Rejected citations: 1.
- Validated source: `https://www.python.org/downloads/`.

The rejected citation demonstrates that application-side citation validation was
actually applied. This is one live research-quality sample, not the complete
90% evidence-relevance or 100% citation-support corpus threshold.

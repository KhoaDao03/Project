# M2 — Real Local Generalist: Implementation Status

**Status:** Complete — owner-approved 2026-08-04; qwen3:8b development profile.

## Implemented

- `adapters/ollama_generalist.py` implements `GeneralistPort` using localhost
  Ollama streaming JSON, bounded output, explicit provider error mapping, and
  cooperative cancellation.
- `composition.py` selects Ollama for non-fake model IDs; the deterministic fake
  remains available for offline tests and compatibility checks.
- Built-in and example configuration select `qwen3:8b` for development/testing;
  qwen3:14b is explicitly selected only through `config.qwen3-14b.example.toml`
  or env. Offline unit tests explicitly select the deterministic fake provider.
- `specialists/` validates and discovers declarative manifests without wiring
  specialist execution or routing.
- `SqliteSessionRepository` creates the configured parent directory on clean start.
- Ctrl+C requests cancellation; cancelled provider calls map to `CANCELLED`, never
  `COMPLETED` or fabricated success.

## Evidence

- Ollama API reachable; `qwen3:14b` and `qwen3:8b` are pulled.
- Deterministic suite: `90 passed, 0 failed`.
- Real adapter smoke: `qwen3:8b` returned non-empty text in `2450 ms`, 7 output
  tokens, through `OllamaGeneralist`.
- Detailed evidence: [`M2_QWEN3_8B_BENCHMARK.md`](M2_QWEN3_8B_BENCHMARK.md).
- Composition health: Ollama, SQLite, and audit all reported healthy.

## Deferred / later evidence

- The qwen3:14b benchmark is intentionally deferred/opt-in because other device
  workloads can exhaust VRAM. qwen3:8b is the development/test benchmarked model;
  qwen3:14b remains available for explicit requests.
- Cancellation now returns `CANCELLED`, preserves received non-thinking output as
  partial work, emits `task.cancelled`, and never reports `COMPLETED`.
- Cancellation evidence: streamed adapter test plus orchestrator integration test
  in `test_ollama_generalist.py` and `test_orchestrator_conversation.py`.

- qwen3:14b benchmarking is intentionally deferred/opt-in because other device
  workloads can exhaust VRAM; it remains available for explicit requests.
- Full release evaluation remains an M7 responsibility.

M2 is complete. M3 is eligible to begin, but no M3 work is included here.

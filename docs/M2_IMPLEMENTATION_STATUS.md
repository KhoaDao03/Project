# M2 — Real Local Generalist: Implementation Status

**Status:** Implemented, tested, and partially verified; milestone remains open.

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
- Deterministic suite: `82 passed, 0 failed`.
- Real adapter smoke: `qwen3:8b` returned non-empty text in `2450 ms`, 7 output
  tokens, through `OllamaGeneralist`.
- Composition health: Ollama, SQLite, and audit all reported healthy.

## Open exit criteria

- The qwen3:14b benchmark is intentionally deferred/opt-in because other device
  workloads can exhaust VRAM. qwen3:8b is the development/test benchmarked model;
  qwen3:14b remains available for explicit requests.
- Full interactive cancellation/partial-work evidence remains pending; current
  cancellation is cooperative and safely prevents a completed result.

M2 must remain open until the owner approves the qwen3:8b benchmark thresholds and
the cancellation evidence.
No M3 work is included.

"""Adapters: concrete implementations of ports.

M1 set:
- FakeGeneralist (DETERMINISTIC FAKE — stands in for the M2 Ollama adapter).
- SqliteSessionRepository (REAL persistence for M1).
- InMemoryAuditLog / structured audit (REAL, redacted).
- SystemClock (REAL) and FixedClock (test fake).
"""

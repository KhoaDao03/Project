"""Presentation layer: terminal (CLI) adapter.

Owns input validation feedback, command parsing, consent display (later), and
response rendering. Does NOT call providers or the database directly (DESIGN §5.2);
it goes through the Application/orchestrator. Interface choice is OQ-02 (terminal
recommended); a web adapter could later reuse the same application surface.
"""

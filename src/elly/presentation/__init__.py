"""Presentation layer: terminal (CLI) adapter.

Owns input validation feedback, command parsing, consent display, and response
rendering. It does not call providers or the database directly; it uses the
public application façade backed by ``AssistantRuntime``. A web adapter can
reuse the same application surface.
"""

"""Shared redaction for audit and public trace metadata.

Trace details are diagnostics, not a second message store.  Known sensitive
key/value fields are replaced before they reach either the durable audit sink or
an interface response.  The allowlist-like field handling keeps prompts,
payloads, private context, and model rationale out of the trace surface while
retaining bounded operational counters and reason codes.
"""

from __future__ import annotations

import re

_MAX_DETAIL = 200
_SENSITIVE_VALUE = re.compile(
    r"(?ix)"
    r"(?P<key>"
    r"api[_ -]?key|secret|password|token|prompt|request|message|answer|content|"
    r"payload|private[_ -]?payload|provider[_ -]?(?:body|response)|"
    r"result[_ -]?body|body|context(?:[_ -]?text)?|model[_ -]?rationale|"
    r"chain[_ -]?of[_ -]?thought|thoughts?"
    r")\s*[:=]\s*"
    r"(?P<value>\"[^\"]*\"|'[^']*'|.*?)(?=\s+[A-Za-z][A-Za-z0-9_.-]*\s*[:=]|$)"
)


def redact_trace_detail(detail: str) -> str:
    """Return a single-line, bounded detail with sensitive values removed."""
    if not isinstance(detail, str):
        return ""
    normalized = " ".join(detail.split())
    redacted = _SENSITIVE_VALUE.sub(lambda match: f"{match.group('key')}=[REDACTED]", normalized)
    return " ".join(redacted.split())[:_MAX_DETAIL]


__all__ = ["redact_trace_detail"]

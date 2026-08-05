"""Typed specialist task/result contracts (AI-003/007/008/013)."""

from __future__ import annotations

from dataclasses import dataclass
import re

from ..domain.errors import ConfigInvalidError


@dataclass(frozen=True, slots=True)
class SpecialistTask:
    task_id: str
    specialist_id: str
    goal: str
    context: str
    privacy_class: str
    approval_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    delegation_depth: int = 1

    def __post_init__(self) -> None:
        for value, name in ((self.task_id, "task_id"), (self.specialist_id, "specialist_id"), (self.goal, "goal")):
            if not isinstance(value, str) or not value.strip():
                raise ConfigInvalidError(f"specialist {name} must be non-empty")
        if self.delegation_depth != 1:
            raise ConfigInvalidError("specialist delegation depth must be exactly one")


@dataclass(frozen=True, slots=True)
class SpecialistResult:
    status: str
    answer: str
    assumptions: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    key_evidence: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    recommended_action: str | None = None
    truncated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.status, str) or not isinstance(self.answer, str):
            raise ConfigInvalidError("specialist status and answer must be strings")
        if self.status not in {"known", "inferred", "unknown", "blocked", "partial"}:
            raise ConfigInvalidError("invalid specialist epistemic status")
        if not self.answer.strip() and self.status not in {"blocked", "unknown", "partial"}:
            raise ConfigInvalidError("successful specialist result requires an answer")
        if len(self.answer) > 12000:
            raise ConfigInvalidError("specialist answer exceeds output ceiling")
        for field_name in ("assumptions", "uncertainties", "key_evidence", "sources"):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or any(not isinstance(value, str) for value in values):
                raise ConfigInvalidError(f"specialist {field_name} must contain only strings")
        if self.recommended_action is not None and not isinstance(self.recommended_action, str):
            raise ConfigInvalidError("specialist recommended_action must be text or null")


def validate_result(result: SpecialistResult, *, allowed_evidence: frozenset[str] = frozenset()) -> SpecialistResult:
    """Reject unsupported evidence and false claims that an action was performed."""
    if allowed_evidence and any(item not in allowed_evidence for item in result.key_evidence):
        raise ConfigInvalidError("specialist cited evidence outside the supplied set")
    if re.search(r"(?i)\b(i|we)\s+(executed|deleted|sent|submitted|purchased|traded|wrote)\b", result.answer):
        raise ConfigInvalidError("specialist falsely claimed a prohibited action was performed")
    return result

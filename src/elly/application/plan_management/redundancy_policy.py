"""Deterministic redundancy checks for validated specialist plans.

The policy operates only on typed proposal metadata.  It does not inspect
provider output, call a model, or decide whether a capability is authorized.
Those boundaries remain owned by the plan validator and later execution phase.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ...planning.contracts import ProposedInput, ProposedStep

_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION = re.compile(r"[^a-z0-9_.-]+")


def normalize_objective(value: str) -> str:
    """Normalize bounded objective text without attempting semantic matching."""

    lowered = value.casefold().strip()
    lowered = _PUNCTUATION.sub(" ", lowered)
    return _WHITESPACE.sub(" ", lowered).strip()


def normalize_input_references(inputs: tuple[ProposedInput, ...]) -> tuple[str, ...]:
    """Return stable, payload-free input references for fingerprinting."""

    return tuple(
        sorted(f"{item.name}:{item.value_type}:{item.source}:{item.reference}" for item in inputs)
    )


def redundancy_fingerprint(step: ProposedStep) -> tuple[object, ...]:
    """Build the stable fingerprint specified by V3-PLAN-003."""

    return (
        step.capability_id,
        step.operation_id,
        step.objective_class,
        step.perspective,
        normalize_input_references(step.inputs),
        step.expected_output_type,
    )


@dataclass(frozen=True, slots=True)
class RedundancyValidation:
    """Pure result of comparing specialist proposal metadata."""

    accepted: bool
    reason_code: str = ""
    duplicate_step_ids: tuple[tuple[str, str], ...] = ()
    fingerprints: tuple[tuple[str, tuple[object, ...]], ...] = ()


class RedundancyPolicy:
    """Reject exact duplicate specialist work unless explicitly verified."""

    def validate(
        self,
        steps: tuple[ProposedStep, ...],
        *,
        verification_requested: bool = False,
    ) -> RedundancyValidation:
        fingerprints = tuple(
            (step.proposal_step_id, redundancy_fingerprint(step)) for step in steps
        )
        seen: dict[tuple[object, ...], ProposedStep] = {}
        duplicates: list[tuple[str, str]] = []
        for step in steps:
            fingerprint = redundancy_fingerprint(step)
            previous = seen.get(fingerprint)
            if previous is None:
                seen[fingerprint] = step
                continue
            duplicates.append((previous.proposal_step_id, step.proposal_step_id))
            if not verification_requested:
                if previous.verification or step.verification:
                    return RedundancyValidation(
                        False,
                        "PLAN_VERIFICATION_UNAUTHORIZED",
                        tuple(duplicates),
                        fingerprints,
                    )
                return RedundancyValidation(
                    False,
                    "PLAN_REDUNDANT_STEP",
                    tuple(duplicates),
                    fingerprints,
                )
            if not (previous.verification or step.verification):
                return RedundancyValidation(
                    False,
                    "PLAN_VERIFICATION_MARKER_REQUIRED",
                    tuple(duplicates),
                    fingerprints,
                )
        return RedundancyValidation(
            True,
            "PLAN_VERIFICATION_ALLOWED" if duplicates else "",
            tuple(duplicates),
            fingerprints,
        )


__all__ = [
    "RedundancyPolicy",
    "RedundancyValidation",
    "normalize_input_references",
    "normalize_objective",
    "redundancy_fingerprint",
]

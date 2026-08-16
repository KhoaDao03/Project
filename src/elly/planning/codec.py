"""Strict JSON codec for the versioned execution-proposal contract."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

from ..domain.errors import InputInvalidError, MalformedResultError
from .contracts import (
    MAX_PROPOSAL_AMBIGUITIES,
    MAX_PROPOSAL_BYTES,
    MAX_PROPOSAL_DEPENDENCIES,
    MAX_PROPOSAL_INPUTS,
    MAX_PROPOSAL_JUSTIFICATION,
    MAX_PROPOSAL_STEPS,
    MAX_PROPOSAL_TEXT,
    PROPOSAL_SCHEMA_VERSION,
    PROPOSED_INPUT_SOURCES,
    ClarificationField,
    ExecutionProposal,
    FinalizationStrategy,
    ProposalDisposition,
    ProposedInput,
    ProposedStep,
)

_PROPOSAL_KEYS = frozenset(
    {
        "schema_version",
        "disposition",
        "steps",
        "finalization",
        "ambiguities",
        "confidence",
        "reason_code",
        "justification",
    }
)
_STEP_KEYS = frozenset(
    {
        "proposal_step_id",
        "capability_id",
        "operation_id",
        "objective",
        "objective_class",
        "perspective",
        "inputs",
        "dependencies",
        "expected_output_type",
        "required",
        "verification",
        "requires_current_information",
        "requires_external_access",
    }
)
_INPUT_KEYS = frozenset({"name", "value_type", "source", "reference", "required"})
_AMBIGUITY_KEYS = frozenset({"field_id", "reason_code", "question", "required"})


def _object(value: object, name: str, allowed: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MalformedResultError(f"planner {name} must be an object")
    data = dict(value)
    keys = set(data)
    if not all(isinstance(key, str) for key in keys):
        raise MalformedResultError(f"planner {name} contains a non-text field")
    unknown = keys - allowed
    if unknown:
        raise MalformedResultError(
            f"planner {name} contains unsupported fields: "
            + ", ".join(sorted(str(item) for item in unknown))
        )
    return cast(dict[str, Any], data)


def _required(value: Mapping[str, Any], keys: frozenset[str], name: str) -> None:
    missing = keys - set(value)
    if missing:
        raise MalformedResultError(
            f"planner {name} is missing required fields: " + ", ".join(sorted(missing))
        )


def _list(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise MalformedResultError(f"planner {name} must be an array")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise MalformedResultError(f"planner {name} must be text")
    return value


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise MalformedResultError(f"planner {name} must be a boolean")
    return value


def _input(value: object) -> ProposedInput:
    data = _object(value, "input", _INPUT_KEYS)
    _required(data, frozenset({"name", "value_type", "source", "reference", "required"}), "input")
    try:
        return ProposedInput(
            name=_string(data["name"], "input.name"),
            value_type=_string(data["value_type"], "input.value_type"),
            source=_string(data["source"], "input.source"),
            reference=_string(data["reference"], "input.reference"),
            required=_bool(data["required"], "input.required"),
        )
    except (InputInvalidError, TypeError, ValueError) as exc:
        raise MalformedResultError("planner input is invalid") from exc


def _step(value: object) -> ProposedStep:
    data = _object(value, "step", _STEP_KEYS)
    required = frozenset(
        {
            "proposal_step_id",
            "capability_id",
            "operation_id",
            "objective",
            "objective_class",
            "perspective",
            "inputs",
            "dependencies",
            "expected_output_type",
            "required",
            "verification",
            "requires_current_information",
            "requires_external_access",
        }
    )
    _required(data, required, "step")
    inputs = tuple(_input(item) for item in _list(data["inputs"], "step.inputs"))
    dependencies_value = _list(data["dependencies"], "step.dependencies")
    dependencies = tuple(_string(item, "step dependency") for item in dependencies_value)
    try:
        return ProposedStep(
            proposal_step_id=_string(data["proposal_step_id"], "step.proposal_step_id"),
            capability_id=_string(data["capability_id"], "step.capability_id"),
            operation_id=_string(data["operation_id"], "step.operation_id"),
            objective=_string(data["objective"], "step.objective"),
            objective_class=_string(data["objective_class"], "step.objective_class"),
            perspective=_string(data["perspective"], "step.perspective"),
            inputs=inputs,
            dependencies=dependencies,
            expected_output_type=_string(data["expected_output_type"], "step.expected_output_type"),
            required=_bool(data["required"], "step.required"),
            verification=_bool(data["verification"], "step.verification"),
            requires_current_information=_bool(
                data["requires_current_information"],
                "step.requires_current_information",
            ),
            requires_external_access=_bool(
                data["requires_external_access"],
                "step.requires_external_access",
            ),
        )
    except (InputInvalidError, TypeError, ValueError) as exc:
        raise MalformedResultError("planner step is invalid") from exc


def _ambiguity(value: object) -> ClarificationField:
    data = _object(value, "ambiguity", _AMBIGUITY_KEYS)
    _required(data, _AMBIGUITY_KEYS, "ambiguity")
    try:
        return ClarificationField(
            field_id=_string(data["field_id"], "ambiguity.field_id"),
            reason_code=_string(data["reason_code"], "ambiguity.reason_code"),
            question=_string(data["question"], "ambiguity.question"),
            required=_bool(data["required"], "ambiguity.required"),
        )
    except (InputInvalidError, TypeError, ValueError) as exc:
        raise MalformedResultError("planner ambiguity is invalid") from exc


def _proposal_from_mapping(value: object) -> ExecutionProposal:
    data = _object(value, "proposal", _PROPOSAL_KEYS)
    _required(data, _PROPOSAL_KEYS, "proposal")
    try:
        steps = tuple(_step(item) for item in _list(data["steps"], "proposal.steps"))
        ambiguities = tuple(
            _ambiguity(item) for item in _list(data["ambiguities"], "proposal.ambiguities")
        )
        return ExecutionProposal(
            schema_version=_string(data["schema_version"], "proposal.schema_version"),
            disposition=ProposalDisposition(_string(data["disposition"], "proposal.disposition")),
            steps=steps,
            finalization=FinalizationStrategy(
                _string(data["finalization"], "proposal.finalization")
            ),
            ambiguities=ambiguities,
            confidence=cast(float, data["confidence"]),
            reason_code=_string(data["reason_code"], "proposal.reason_code"),
            justification=_string(data["justification"], "proposal.justification"),
        )
    except (InputInvalidError, TypeError, ValueError, KeyError) as exc:
        raise MalformedResultError("planner proposal is invalid") from exc


def decode_proposal(payload: str | bytes | Mapping[str, object]) -> ExecutionProposal:
    """Decode one strict JSON proposal and reject unknown/oversized fields."""
    if isinstance(payload, bytes):
        if len(payload) > MAX_PROPOSAL_BYTES:
            raise MalformedResultError("planner proposal exceeds its size limit")
        try:
            decoded: object = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MalformedResultError("planner proposal is not valid JSON") from exc
    elif isinstance(payload, str):
        if len(payload.encode("utf-8")) > MAX_PROPOSAL_BYTES:
            raise MalformedResultError("planner proposal exceeds its size limit")
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise MalformedResultError("planner proposal is not valid JSON") from exc
    elif isinstance(payload, Mapping):
        decoded = dict(payload)
        try:
            encoded_size = len(
                json.dumps(decoded, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
        except (TypeError, ValueError) as exc:
            raise MalformedResultError("planner proposal contains non-JSON values") from exc
        if encoded_size > MAX_PROPOSAL_BYTES:
            raise MalformedResultError("planner proposal exceeds its size limit")
    else:
        raise MalformedResultError("planner proposal must be JSON text")
    return _proposal_from_mapping(decoded)


def proposal_to_dict(proposal: ExecutionProposal) -> dict[str, object]:
    """Return the canonical JSON-compatible representation of a proposal."""
    if not isinstance(proposal, ExecutionProposal):
        raise InputInvalidError("proposal must be an ExecutionProposal")
    return {
        "schema_version": proposal.schema_version,
        "disposition": proposal.disposition.value,
        "steps": [
            {
                "proposal_step_id": step.proposal_step_id,
                "capability_id": step.capability_id,
                "operation_id": step.operation_id,
                "objective": step.objective,
                "objective_class": step.objective_class,
                "perspective": step.perspective,
                "inputs": [
                    {
                        "name": item.name,
                        "value_type": item.value_type,
                        "source": item.source,
                        "reference": item.reference,
                        "required": item.required,
                    }
                    for item in step.inputs
                ],
                "dependencies": list(step.dependencies),
                "expected_output_type": step.expected_output_type,
                "required": step.required,
                "verification": step.verification,
                "requires_current_information": step.requires_current_information,
                "requires_external_access": step.requires_external_access,
            }
            for step in proposal.steps
        ],
        "finalization": proposal.finalization.value,
        "ambiguities": [
            {
                "field_id": ambiguity.field_id,
                "reason_code": ambiguity.reason_code,
                "question": ambiguity.question,
                "required": ambiguity.required,
            }
            for ambiguity in proposal.ambiguities
        ],
        "confidence": proposal.confidence,
        "reason_code": proposal.reason_code,
        "justification": proposal.justification,
    }


def encode_proposal(proposal: ExecutionProposal) -> str:
    """Encode a proposal with deterministic ordering and a hard size ceiling."""
    value = json.dumps(
        proposal_to_dict(proposal),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(value.encode("utf-8")) > MAX_PROPOSAL_BYTES:
        raise InputInvalidError("proposal exceeds its size limit")
    return value


def proposal_json_schema() -> dict[str, object]:
    """Return a strict JSON schema suitable for a structured local-model call."""
    identifier = {"type": "string", "pattern": r"^[A-Za-z][A-Za-z0-9_.:-]{0,63}$"}
    code = {"type": "string", "pattern": r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$"}
    input_schema: dict[str, object] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "name": identifier,
            "value_type": identifier,
            "source": {"type": "string", "enum": sorted(PROPOSED_INPUT_SOURCES)},
            "reference": {"type": "string", "maxLength": 128},
            "required": {"type": "boolean"},
        },
        "required": ["name", "value_type", "source", "reference", "required"],
    }
    step_schema: dict[str, object] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "proposal_step_id": identifier,
            "capability_id": identifier,
            "operation_id": identifier,
            "objective": {"type": "string", "maxLength": MAX_PROPOSAL_TEXT},
            "objective_class": code,
            "perspective": code,
            "inputs": {
                "type": "array",
                "items": input_schema,
                "maxItems": MAX_PROPOSAL_INPUTS,
            },
            "dependencies": {
                "type": "array",
                "items": identifier,
                "maxItems": MAX_PROPOSAL_DEPENDENCIES,
            },
            "expected_output_type": identifier,
            "required": {"type": "boolean"},
            "verification": {"type": "boolean"},
            "requires_current_information": {"type": "boolean"},
            "requires_external_access": {"type": "boolean"},
        },
        "required": sorted(_STEP_KEYS),
    }
    ambiguity_schema: dict[str, object] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "field_id": code,
            "reason_code": code,
            "question": {"type": "string", "maxLength": MAX_PROPOSAL_TEXT},
            "required": {"type": "boolean"},
        },
        "required": sorted(_AMBIGUITY_KEYS),
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"const": PROPOSAL_SCHEMA_VERSION},
            "disposition": {"type": "string", "enum": [item.value for item in ProposalDisposition]},
            "steps": {
                "type": "array",
                "items": step_schema,
                "maxItems": MAX_PROPOSAL_STEPS,
            },
            "finalization": {
                "type": "string",
                "enum": [item.value for item in FinalizationStrategy],
            },
            "ambiguities": {
                "type": "array",
                "items": ambiguity_schema,
                "maxItems": MAX_PROPOSAL_AMBIGUITIES,
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason_code": code,
            "justification": {"type": "string", "maxLength": MAX_PROPOSAL_JUSTIFICATION},
        },
        "required": sorted(_PROPOSAL_KEYS),
    }


__all__ = [
    "decode_proposal",
    "encode_proposal",
    "proposal_json_schema",
    "proposal_to_dict",
]

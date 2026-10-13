from __future__ import annotations

from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.capabilities.model.request.prompt.api.unit_semantics import (
    output_schema_id,
    output_schema_unit,
    require_output_schema,
)


class OutputSchemaRegistry:
    """Dynamic lookup index over immutable output-schema Units."""

    def __init__(self, specs: tuple[NoetriumUnit, ...] = ()) -> None:
        self._specs: dict[str, NoetriumUnit] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: NoetriumUnit) -> None:
        spec = require_output_schema(spec)
        key = output_schema_id(spec)
        current = self._specs.get(key)
        if current is not None and current != spec:
            raise ValueError(f"schema redefined: {key}")
        self._specs[key] = spec

    def require(self, schema_id: str) -> NoetriumUnit:
        try:
            return self._specs[schema_id]
        except KeyError as exc:
            raise KeyError(f"unknown output schema: {schema_id}") from exc


def default_output_schemas() -> OutputSchemaRegistry:
    obj = lambda required, props: {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": props,
    }
    scalar = {
        "string": {"type": "string"},
        "bool": {"type": "boolean"},
        "number": {"type": "number"},
    }
    return OutputSchemaRegistry(
        (
            output_schema_unit(
                "planner_action_v2",
                "2.0",
                obj(
                    ["action_type", "arguments"],
                    {
                        "action_type": scalar["string"],
                        "arguments": {"type": "object"},
                        "completion_claim": scalar["bool"],
                    },
                ),
            ),
            output_schema_unit(
                "semantic_derivation_v2",
                "2.0",
                obj(["records"], {"records": {"type": "array"}}),
            ),
            output_schema_unit(
                "structural_intent_v2",
                "2.0",
                obj(
                    ["edit", "rationale", "evidence_refs"],
                    {
                        "edit": {
                            "type": "string",
                            "enum": ["NO_EDIT", "CREATE", "RETIRE", "SPLIT", "MERGE"],
                        },
                        "rationale": scalar["string"],
                        "evidence_refs": {"type": "array"},
                    },
                ),
            ),
            output_schema_unit(
                "diagnostic_summary_v2",
                "2.0",
                obj(
                    [
                        "proven_cause",
                        "correlated_evidence",
                        "unknowns",
                        "next_action",
                    ],
                    {
                        "proven_cause": scalar["string"],
                        "correlated_evidence": {"type": "array"},
                        "unknowns": {"type": "array"},
                        "next_action": scalar["string"],
                    },
                ),
            ),
        )
    )


__all__ = ["OutputSchemaRegistry", "default_output_schemas"]

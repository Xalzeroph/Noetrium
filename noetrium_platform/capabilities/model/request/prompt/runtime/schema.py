from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib

from noetrium_platform.foundation.kernel.kernel import JsonObject, canonical_bytes, freeze_json


@dataclass(frozen=True, slots=True)
class OutputSchemaSpec:
    schema_id: str
    version: str
    schema: JsonObject

    def __post_init__(self) -> None:
        if not isinstance(self.schema, Mapping):
            raise TypeError("output schema must be a mapping")
        object.__setattr__(self, "schema", freeze_json(self.schema))

    def digest(self) -> str:
        raw=canonical_bytes({"schema_id":self.schema_id,"version":self.version,"schema":self.schema})
        return hashlib.sha256(raw).hexdigest()


class OutputSchemaRegistry:
    def __init__(self, specs: tuple[OutputSchemaSpec,...]=()) -> None:
        self._specs: dict[str,OutputSchemaSpec]={}
        for s in specs: self.register(s)

    def register(self, spec: OutputSchemaSpec) -> None:
        if spec.schema_id in self._specs and self._specs[spec.schema_id] != spec:
            raise ValueError(f"schema redefined: {spec.schema_id}")
        self._specs[spec.schema_id]=spec

    def require(self, schema_id: str) -> OutputSchemaSpec:
        try: return self._specs[schema_id]
        except KeyError as exc: raise KeyError(f"unknown output schema: {schema_id}") from exc


def default_output_schemas() -> OutputSchemaRegistry:
    obj=lambda required,props:{"type":"object","additionalProperties":False,"required":required,"properties":props}
    S={
        "string":{"type":"string"}, "bool":{"type":"boolean"}, "number":{"type":"number"},
    }
    return OutputSchemaRegistry((
        OutputSchemaSpec("planner_action_v2","2.0",obj(["action_type","arguments"],{"action_type":S["string"],"arguments":{"type":"object"},"completion_claim":S["bool"]})),
        OutputSchemaSpec("semantic_derivation_v2","2.0",obj(["records"],{"records":{"type":"array"}})),
        OutputSchemaSpec("structural_intent_v2","2.0",obj(["edit","rationale","evidence_refs"],{"edit":{"type":"string","enum":["NO_EDIT","CREATE","RETIRE","SPLIT","MERGE"]},"rationale":S["string"],"evidence_refs":{"type":"array"}})),
        OutputSchemaSpec("diagnostic_summary_v2","2.0",obj(["proven_cause","correlated_evidence","unknowns","next_action"],{"proven_cause":S["string"],"correlated_evidence":{"type":"array"},"unknowns":{"type":"array"},"next_action":S["string"]})),
    ))

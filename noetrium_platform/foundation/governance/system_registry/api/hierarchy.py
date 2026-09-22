from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
import json

LAYER_HIERARCHY_SCHEMA = "noetrium-layer-hierarchy.v4"


@dataclass(frozen=True, slots=True)
class LayerDescriptor:
    layer_id: str
    lower_layer_id: str | None
    members: tuple[str, ...]
    facade_module: str
    composition_prefix: str | None


@dataclass(frozen=True, slots=True)
class SideplaneDescriptor:
    sideplane_id: str
    system_id: str
    base_layer_id: str
    facade_module: str
    attachment_mode: str = "application_composition"


@dataclass(frozen=True, slots=True)
class LayerHierarchy:
    layers: tuple[LayerDescriptor, ...]
    global_contract_prefixes: tuple[str, ...]
    application_composition_prefix: str
    global_systems: tuple[str, ...] = ()
    sideplanes: tuple[SideplaneDescriptor, ...] = ()

    def __post_init__(self) -> None:
        ids = tuple(layer.layer_id for layer in self.layers)
        if len(ids) != len(set(ids)):
            raise ValueError("layer ids must be unique")

        members = tuple(member for layer in self.layers for member in layer.members)
        if len(members) != len(set(members)):
            raise ValueError("a system may belong to only one layer")

        if len(self.global_systems) != len(set(self.global_systems)):
            raise ValueError("global systems must be unique")
        overlap = set(members).intersection(self.global_systems)
        if overlap:
            raise ValueError(
                "global systems cannot also be layered: "
                + ", ".join(sorted(overlap))
            )

        sideplane_ids = tuple(row.sideplane_id for row in self.sideplanes)
        sideplane_systems = tuple(row.system_id for row in self.sideplanes)
        if len(sideplane_ids) != len(set(sideplane_ids)):
            raise ValueError("sideplane ids must be unique")
        if len(sideplane_systems) != len(set(sideplane_systems)):
            raise ValueError("a system may belong to only one sideplane")
        illegal = set(sideplane_systems).intersection(set(members) | set(self.global_systems))
        if illegal:
            raise ValueError(
                "sideplane systems cannot also be layered/global: "
                + ", ".join(sorted(illegal))
            )

        known = set(ids)
        for sideplane in self.sideplanes:
            if sideplane.base_layer_id not in known:
                raise ValueError(
                    f"unknown sideplane base layer: {sideplane.base_layer_id}"
                )
            if sideplane.attachment_mode != "application_composition":
                raise ValueError(
                    f"unsupported sideplane attachment mode: {sideplane.attachment_mode}"
                )
        for layer in self.layers:
            if (
                layer.lower_layer_id is not None
                and layer.lower_layer_id not in known
            ):
                raise ValueError(
                    f"unknown lower layer: {layer.lower_layer_id}"
                )
            if layer.lower_layer_id == layer.layer_id:
                raise ValueError("layer cannot depend on itself")

        by_id = {layer.layer_id: layer for layer in self.layers}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(layer_id: str) -> None:
            if layer_id in visited:
                return
            if layer_id in visiting:
                raise ValueError(f"layer cycle at {layer_id}")
            visiting.add(layer_id)
            lower = by_id[layer_id].lower_layer_id
            if lower is not None:
                visit(lower)
            visiting.remove(layer_id)
            visited.add(layer_id)

        for layer_id in ids:
            visit(layer_id)

    def layer(self, layer_id: str) -> LayerDescriptor:
        for layer in self.layers:
            if layer.layer_id == layer_id:
                return layer
        raise KeyError(layer_id)

    def layer_for_system(self, system_id: str) -> LayerDescriptor:
        for layer in self.layers:
            if system_id in layer.members:
                return layer
        raise KeyError(system_id)

    def is_global_system(self, system_id: str) -> bool:
        return system_id in self.global_systems

    def is_sideplane_system(self, system_id: str) -> bool:
        return any(row.system_id == system_id for row in self.sideplanes)

    def sideplane_for_system(self, system_id: str) -> SideplaneDescriptor:
        for row in self.sideplanes:
            if row.system_id == system_id:
                return row
        raise KeyError(system_id)

    def lower_layer(self, system_id: str) -> LayerDescriptor | None:
        if self.is_global_system(system_id):
            return None
        layer = self.layer_for_system(system_id)
        return (
            None
            if layer.lower_layer_id is None
            else self.layer(layer.lower_layer_id)
        )

    def is_global_contract(self, module: str) -> bool:
        return any(
            module == prefix or module.startswith(prefix + ".")
            for prefix in self.global_contract_prefixes
        )


@lru_cache(maxsize=1)
def layer_hierarchy() -> LayerHierarchy:
    resource = files(
        "noetrium_platform.foundation.governance.system_registry"
    ).joinpath("hierarchy.json")
    raw = json.loads(resource.read_text(encoding="utf-8"))
    if raw.get("schema") != LAYER_HIERARCHY_SCHEMA:
        raise RuntimeError(
            "unsupported layer hierarchy schema: "
            f"{raw.get('schema')!r}; expected {LAYER_HIERARCHY_SCHEMA!r}"
        )

    rows = raw.get("layers")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("layer hierarchy must declare layers")

    parsed: list[LayerDescriptor] = []
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("invalid layer descriptor")
        parsed.append(
            LayerDescriptor(
                layer_id=str(row["id"]),
                lower_layer_id=(
                    None
                    if row.get("lower") is None
                    else str(row["lower"])
                ),
                members=tuple(str(x) for x in row.get("members", ())),
                facade_module=str(row["facade"]),
                composition_prefix=(
                    None
                    if row.get("composition") is None
                    else str(row["composition"])
                ),
            )
        )

    sideplanes_raw = raw.get("sideplanes", ())
    if not isinstance(sideplanes_raw, list):
        raise RuntimeError("layer hierarchy sideplanes must be a list")
    sideplanes: list[SideplaneDescriptor] = []
    for row in sideplanes_raw:
        if not isinstance(row, dict):
            raise RuntimeError("invalid sideplane descriptor")
        sideplanes.append(
            SideplaneDescriptor(
                sideplane_id=str(row["id"]),
                system_id=str(row["system"]),
                base_layer_id=str(row["base"]),
                facade_module=str(row["facade"]),
                attachment_mode=str(
                    row.get("attachment", "application_composition")
                ),
            )
        )

    return LayerHierarchy(
        layers=tuple(parsed),
        global_contract_prefixes=tuple(
            str(x) for x in raw.get("global_contract_prefixes", ())
        ),
        application_composition_prefix=str(
            raw.get(
                "application_composition",
                "noetrium_platform.composition",
            )
        ),
        global_systems=tuple(
            str(x) for x in raw.get("global_systems", ())
        ),
        sideplanes=tuple(sideplanes),
    )


__all__ = [
    "LAYER_HIERARCHY_SCHEMA",
    "LayerDescriptor",
    "LayerHierarchy",
    "SideplaneDescriptor",
    "layer_hierarchy",
]

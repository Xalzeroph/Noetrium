"""Typed top-level blueprint for generating downstream Research OS projects.

A blueprint does not own execution or scientific truth.  It reuses the canonical
ResearchProgram/ResearchPortfolio graph and only marks unresolved definitions
that downstream authors must fill with implementations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json

from noetrium_platform.foundation.kernel.kernel import (
    canonical_digest,
    thaw_json,
)

from .research_os import (
    ResearchDefinition,
    ResearchDefinitionKind,
    ResearchDependency,
    ResearchInputBinding,
    ResearchNode,
    ResearchNodeKind,
    ResearchNodeRef,
    ResearchOutputSpec,
    ResearchPortfolio,
    ResearchPortfolioDependency,
    ResearchProgram,
    ResearchValueKind,
)


RESEARCH_PROJECT_BLUEPRINT_SCHEMA = "noetrium.research-project-blueprint.v1"


@dataclass(frozen=True, slots=True)
class ResearchDefinitionRef:
    program_id: str
    definition_id: str

    def __post_init__(self) -> None:
        # Reuse canonical token validation through ResearchNodeRef without
        # introducing a second identifier grammar.
        ResearchNodeRef(self.program_id, self.definition_id)


@dataclass(frozen=True, slots=True)
class ResearchProjectBlueprint:
    """Immutable authoring plan used to generate a downstream fill-in scaffold."""

    portfolio: ResearchPortfolio
    implementation_slots: tuple[ResearchDefinitionRef, ...] = ()
    blueprint_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.portfolio) is not ResearchPortfolio:
            raise TypeError("research project blueprint requires ResearchPortfolio")
        if type(self.implementation_slots) is not tuple or any(
            type(row) is not ResearchDefinitionRef
            for row in self.implementation_slots
        ):
            raise TypeError(
                "research project blueprint implementation_slots must be typed tuple"
            )
        slots = tuple(
            sorted(
                self.implementation_slots,
                key=lambda row: (row.program_id, row.definition_id),
            )
        )
        if len(slots) != len(set(slots)):
            raise ValueError("research project blueprint slots must be unique")

        definitions = {
            (program.program_id, definition.definition_id): definition
            for program in self.portfolio.programs
            for definition in program.definitions
        }
        bound = tuple(
            sorted(
                key
                for key, definition in definitions.items()
                if definition.implementation is not None
            )
        )
        if bound:
            raise ValueError(
                "research project blueprint must be implementation-free; "
                f"bound_definitions={bound}"
            )
        unknown = tuple(
            (slot.program_id, slot.definition_id)
            for slot in slots
            if (slot.program_id, slot.definition_id) not in definitions
        )
        if unknown:
            raise ValueError(
                "research project blueprint slots reference unknown definitions: "
                f"{unknown}"
            )
        object.__setattr__(self, "implementation_slots", slots)
        object.__setattr__(
            self,
            "blueprint_digest",
            canonical_digest(research_project_blueprint_document(self)),
        )


def research_project_blueprint_document(
    blueprint: ResearchProjectBlueprint,
) -> dict[str, object]:
    if type(blueprint) is not ResearchProjectBlueprint:
        raise TypeError("research blueprint document requires typed blueprint")
    return {
        "schema": RESEARCH_PROJECT_BLUEPRINT_SCHEMA,
        "portfolio_id": blueprint.portfolio.portfolio_id,
        "implementation_slots": [
            {
                "program_id": slot.program_id,
                "definition_id": slot.definition_id,
            }
            for slot in blueprint.implementation_slots
        ],
        "programs": [
            {
                "program_id": program.program_id,
                "definitions": [
                    {
                        "definition_id": definition.definition_id,
                        "kind": definition.kind.value,
                        "config": thaw_json(definition.config),
                    }
                    for definition in program.definitions
                ],
                "nodes": [
                    {
                        "node_id": node.node_id,
                        "kind": node.kind.value,
                        "definition_ids": list(node.definition_ids),
                        "outputs": [
                            {"name": output.name, "kind": output.kind.value}
                            for output in node.outputs
                        ],
                        "config": thaw_json(node.config),
                    }
                    for node in program.nodes
                ],
                "dependencies": [
                    {
                        "upstream_node_id": dependency.upstream_node_id,
                        "downstream_node_id": dependency.downstream_node_id,
                        "bindings": [
                            {
                                "input_name": binding.input_name,
                                "output_name": binding.output_name,
                                "kind": binding.kind.value,
                            }
                            for binding in dependency.bindings
                        ],
                    }
                    for dependency in program.dependencies
                ],
            }
            for program in blueprint.portfolio.programs
        ],
        "dependencies": [
            {
                "upstream": {
                    "program_id": dependency.upstream.program_id,
                    "node_id": dependency.upstream.node_id,
                },
                "downstream": {
                    "program_id": dependency.downstream.program_id,
                    "node_id": dependency.downstream.node_id,
                },
                "bindings": [
                    {
                        "input_name": binding.input_name,
                        "output_name": binding.output_name,
                        "kind": binding.kind.value,
                    }
                    for binding in dependency.bindings
                ],
            }
            for dependency in blueprint.portfolio.dependencies
        ],
    }


def encode_research_project_blueprint(
    blueprint: ResearchProjectBlueprint,
) -> bytes:
    return (
        json.dumps(
            research_project_blueprint_document(blueprint),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise TypeError(f"{field_name} must be an object")
    return value


def _sequence(value: object, field_name: str) -> list[object]:
    if type(value) is not list:
        raise TypeError(f"{field_name} must be an array")
    return value


def _exact_keys(
    row: dict[str, object],
    expected: frozenset[str],
    field_name: str,
) -> None:
    actual = frozenset(row)
    if actual != expected:
        raise ValueError(
            f"{field_name} fields drifted: "
            f"missing={tuple(sorted(expected - actual))} "
            f"unknown={tuple(sorted(actual - expected))}"
        )


def _binding(row: object, field_name: str) -> ResearchInputBinding:
    value = _mapping(row, field_name)
    _exact_keys(
        value,
        frozenset({"input_name", "output_name", "kind"}),
        field_name,
    )
    return ResearchInputBinding(
        str(value["input_name"]),
        str(value["output_name"]),
        ResearchValueKind(str(value["kind"])),
    )


def decode_research_project_blueprint(
    payload: bytes | str,
) -> ResearchProjectBlueprint:
    if isinstance(payload, bytes):
        text = payload.decode("utf-8")
    elif type(payload) is str:
        text = payload
    else:
        raise TypeError("research blueprint payload must be UTF-8 bytes or text")
    document = json.loads(text)
    root = _mapping(document, "research blueprint")
    _exact_keys(
        root,
        frozenset(
            {
                "schema",
                "portfolio_id",
                "implementation_slots",
                "programs",
                "dependencies",
            }
        ),
        "research blueprint",
    )
    if root["schema"] != RESEARCH_PROJECT_BLUEPRINT_SCHEMA:
        raise ValueError("research project blueprint schema is unsupported")

    programs: list[ResearchProgram] = []
    for program_index, raw_program in enumerate(
        _sequence(root["programs"], "research blueprint programs")
    ):
        program_row = _mapping(
            raw_program,
            f"research blueprint programs[{program_index}]",
        )
        _exact_keys(
            program_row,
            frozenset(
                {"program_id", "definitions", "nodes", "dependencies"}
            ),
            f"research blueprint programs[{program_index}]",
        )
        definitions: list[ResearchDefinition] = []
        for definition_index, raw_definition in enumerate(
            _sequence(
                program_row["definitions"],
                f"research blueprint programs[{program_index}].definitions",
            )
        ):
            row = _mapping(
                raw_definition,
                (
                    f"research blueprint programs[{program_index}]"
                    f".definitions[{definition_index}]"
                ),
            )
            _exact_keys(
                row,
                frozenset({"definition_id", "kind", "config"}),
                "research blueprint definition",
            )
            definitions.append(
                ResearchDefinition(
                    str(row["definition_id"]),
                    ResearchDefinitionKind(str(row["kind"])),
                    None,
                    row["config"],
                )
            )

        nodes: list[ResearchNode] = []
        for node_index, raw_node in enumerate(
            _sequence(
                program_row["nodes"],
                f"research blueprint programs[{program_index}].nodes",
            )
        ):
            row = _mapping(raw_node, "research blueprint node")
            _exact_keys(
                row,
                frozenset(
                    {
                        "node_id",
                        "kind",
                        "definition_ids",
                        "outputs",
                        "config",
                    }
                ),
                "research blueprint node",
            )
            outputs = tuple(
                ResearchOutputSpec(
                    str(_mapping(output, "research blueprint output")["name"]),
                    ResearchValueKind(
                        str(_mapping(output, "research blueprint output")["kind"])
                    ),
                )
                for output in _sequence(
                    row["outputs"],
                    "research blueprint node outputs",
                )
            )
            definition_ids = tuple(
                str(value)
                for value in _sequence(
                    row["definition_ids"],
                    "research blueprint node definition_ids",
                )
            )
            nodes.append(
                ResearchNode(
                    str(row["node_id"]),
                    ResearchNodeKind(str(row["kind"])),
                    definition_ids,
                    outputs,
                    row["config"],
                )
            )

        dependencies = tuple(
            ResearchDependency(
                str(_mapping(raw_dependency, "research dependency")["upstream_node_id"]),
                str(_mapping(raw_dependency, "research dependency")["downstream_node_id"]),
                tuple(
                    _binding(binding, "research dependency binding")
                    for binding in _sequence(
                        _mapping(raw_dependency, "research dependency")["bindings"],
                        "research dependency bindings",
                    )
                ),
            )
            for raw_dependency in _sequence(
                program_row["dependencies"],
                f"research blueprint programs[{program_index}].dependencies",
            )
        )
        programs.append(
            ResearchProgram(
                str(program_row["program_id"]),
                tuple(definitions),
                tuple(nodes),
                dependencies,
            )
        )

    portfolio_dependencies: list[ResearchPortfolioDependency] = []
    for raw_dependency in _sequence(
        root["dependencies"],
        "research blueprint dependencies",
    ):
        row = _mapping(raw_dependency, "research portfolio dependency")
        _exact_keys(
            row,
            frozenset({"upstream", "downstream", "bindings"}),
            "research portfolio dependency",
        )
        upstream = _mapping(row["upstream"], "research portfolio upstream")
        downstream = _mapping(row["downstream"], "research portfolio downstream")
        _exact_keys(
            upstream,
            frozenset({"program_id", "node_id"}),
            "research portfolio upstream",
        )
        _exact_keys(
            downstream,
            frozenset({"program_id", "node_id"}),
            "research portfolio downstream",
        )
        portfolio_dependencies.append(
            ResearchPortfolioDependency(
                ResearchNodeRef(
                    str(upstream["program_id"]),
                    str(upstream["node_id"]),
                ),
                ResearchNodeRef(
                    str(downstream["program_id"]),
                    str(downstream["node_id"]),
                ),
                tuple(
                    _binding(binding, "research portfolio dependency binding")
                    for binding in _sequence(
                        row["bindings"],
                        "research portfolio dependency bindings",
                    )
                ),
            )
        )

    slots = tuple(
        ResearchDefinitionRef(
            str(_mapping(raw_slot, "research blueprint slot")["program_id"]),
            str(_mapping(raw_slot, "research blueprint slot")["definition_id"]),
        )
        for raw_slot in _sequence(
            root["implementation_slots"],
            "research blueprint implementation_slots",
        )
    )
    return ResearchProjectBlueprint(
        ResearchPortfolio(
            str(root["portfolio_id"]),
            tuple(programs),
            tuple(portfolio_dependencies),
        ),
        slots,
    )


__all__ = [
    "RESEARCH_PROJECT_BLUEPRINT_SCHEMA",
    "ResearchDefinitionRef",
    "ResearchProjectBlueprint",
    "decode_research_project_blueprint",
    "encode_research_project_blueprint",
    "research_project_blueprint_document",
]

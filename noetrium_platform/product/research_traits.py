"""Canonical built-in scientific vocabulary for the recursive Research Graph.

This module owns *semantic vocabulary*, not execution.  Product authoring and
schema generation consume the same contracts; Composition separately owns how
executable traits lower into runtime machinery.  Unknown traits remain valid so
paper-specific semantics never require a kernel edit.
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from threading import RLock
from types import MappingProxyType

from noetrium_platform.foundation.kernel.structure import (
    GraphPortMode,
    strongly_connected_components,
    NoetriumUnit,
    endpoint_child_id,
    endpoint_port_name,
    port_mode,
    relation_id,
)


TRAIT_PORTFOLIO = "research.portfolio"
TRAIT_PROGRAM = "research.program"
TRAIT_METHOD = "research.method"
TRAIT_STUDY = "research.study"
TRAIT_EXPERIMENT = "research.experiment"
TRAIT_TRIAL = "research.trial"
TRAIT_ABLATION = "research.ablation"
TRAIT_ROBUSTNESS = "research.robustness"
TRAIT_SCALING = "research.scaling"
TRAIT_RUN = "research.run"
TRAIT_EVALUATION = "research.evaluation"
TRAIT_OPTIMIZATION = "research.optimization"
TRAIT_ANALYSIS = "research.analysis"
TRAIT_SELECTION = "research.selection"
TRAIT_FIGURE = "research.figure"
TRAIT_TABLE = "research.table"
TRAIT_PUBLICATION = "research.publication"
TRAIT_RUNTIME = "research.runtime"
TRAIT_BENCHMARK = "research.benchmark"
TRAIT_DATASET = "research.dataset"
TRAIT_METRIC = "research.metric"
TRAIT_CONFIGURATION = "research.configuration"
TRAIT_MODEL = "research.model"
TRAIT_ENVIRONMENT = "research.environment"
TRAIT_PARTICIPANT = "research.participant"
TRAIT_PROTOCOL = "research.protocol"
TRAIT_TRIAL_PROVIDER = "research.trial-provider"
TRAIT_VERIFIER = "research.verifier"
TRAIT_UNIT_ACTIVATION = "research.unit-activation"
TRAIT_HYPOTHESIS = "research.hypothesis"
TRAIT_CLAIM = "research.claim"
TRAIT_FACTOR = "research.factor"
TRAIT_TREATMENT = "research.treatment"
TRAIT_INTERVENTION = "research.intervention"
TRAIT_COHORT = "research.cohort"
TRAIT_TASK = "research.task"
TRAIT_SPLIT = "research.split"
TRAIT_MEASUREMENT = "research.measurement"
TRAIT_ARTIFACT = "research.artifact"
TRAIT_EVIDENCE = "research.evidence"
TRAIT_REPORT = "research.report"
TRAIT_OBJECTIVE = "research.objective"
TRAIT_LOOP_PROGRESS = "research.loop-progress"

RELATION_FLOW = "research.flow"


ORGANIZATIONAL_TRAITS = frozenset({TRAIT_PORTFOLIO, TRAIT_PROGRAM})
PLATFORM_BINDING_TRAITS = frozenset({
    TRAIT_BENCHMARK, TRAIT_CONFIGURATION, TRAIT_DATASET, TRAIT_ENVIRONMENT,
    TRAIT_MODEL, TRAIT_PARTICIPANT, TRAIT_PROTOCOL, TRAIT_TRIAL_PROVIDER,
    TRAIT_VERIFIER,
})
SCIENTIFIC_METADATA_TRAITS = frozenset({
    TRAIT_ARTIFACT, TRAIT_CLAIM, TRAIT_COHORT, TRAIT_EVIDENCE, TRAIT_FACTOR,
    TRAIT_HYPOTHESIS, TRAIT_INTERVENTION, TRAIT_MEASUREMENT, TRAIT_OBJECTIVE,
    TRAIT_REPORT, TRAIT_SPLIT, TRAIT_TASK, TRAIT_TREATMENT,
})

# Literal single authority consumed both at runtime and by AST-only schema generation.
# recognized_parameters are guidance/diagnostics, not a closed-world restriction.
# structured_parameters are fail-closed when present. Unknown parameters remain legal.
_TRAIT_CONTRACT_SPEC = {
    TRAIT_PORTFOLIO: {"locations": ("graph",), "recognized_parameters": (), "structured_parameters": (), "exclusive_parameter_groups": ()},
    TRAIT_PROGRAM: {"locations": ("graph",), "recognized_parameters": ("title", "version", "authors", "tags"), "structured_parameters": (), "exclusive_parameter_groups": ()},
    TRAIT_METHOD: {"locations": ("graph", "symbol"), "recognized_parameters": ("entrypoint", "method_id", "version", "semantic_contract", "configuration", "execution", "evidence", "metrics", "artifacts", "state_schema", "input_schema", "output_schema", "args", "kwargs"), "structured_parameters": ("configuration", "kwargs"), "exclusive_parameter_groups": ()},
    TRAIT_STUDY: {"locations": ("graph",), "recognized_parameters": ("study", "design", "factors", "treatments", "repetitions", "seeds", "blocking", "stopping"), "structured_parameters": ("study", "design", "blocking", "stopping"), "exclusive_parameter_groups": ()},
    TRAIT_EXPERIMENT: {"locations": ("graph",), "recognized_parameters": ("study", "design", "factors", "treatments", "repetitions", "seeds", "blocking", "stopping"), "structured_parameters": ("study", "design", "blocking", "stopping"), "exclusive_parameter_groups": ()},
    TRAIT_TRIAL: {"locations": ("graph",), "recognized_parameters": ("assignment", "seed", "intervention", "limits"), "structured_parameters": ("assignment", "intervention", "limits"), "exclusive_parameter_groups": ()},
    TRAIT_ABLATION: {"locations": ("graph",), "recognized_parameters": ("study", "factors", "treatments", "repetitions", "seeds"), "structured_parameters": ("study",), "exclusive_parameter_groups": ()},
    TRAIT_ROBUSTNESS: {"locations": ("graph",), "recognized_parameters": ("study", "factors", "treatments", "repetitions", "seeds"), "structured_parameters": ("study",), "exclusive_parameter_groups": ()},
    TRAIT_SCALING: {"locations": ("graph",), "recognized_parameters": ("study", "factors", "treatments", "repetitions", "seeds"), "structured_parameters": ("study",), "exclusive_parameter_groups": ()},
    TRAIT_RUN: {"locations": ("graph",), "recognized_parameters": ("configuration",), "structured_parameters": ("configuration",), "exclusive_parameter_groups": ()},
    TRAIT_EVALUATION: {"locations": ("graph",), "recognized_parameters": ("configuration",), "structured_parameters": ("configuration",), "exclusive_parameter_groups": ()},
    TRAIT_OPTIMIZATION: {"locations": ("graph",), "recognized_parameters": ("objective", "constraints", "search_space", "budget"), "structured_parameters": ("search_space",), "exclusive_parameter_groups": ()},
    TRAIT_ANALYSIS: {"locations": ("graph", "symbol"), "recognized_parameters": ("analysis",), "structured_parameters": ("analysis",), "exclusive_parameter_groups": ()},
    TRAIT_SELECTION: {"locations": ("graph", "symbol"), "recognized_parameters": ("criterion", "constraints", "tie_break"), "structured_parameters": (), "exclusive_parameter_groups": ()},
    TRAIT_FIGURE: {"locations": ("graph", "symbol"), "recognized_parameters": ("figure",), "structured_parameters": ("figure",), "exclusive_parameter_groups": ()},
    TRAIT_TABLE: {"locations": ("graph", "symbol"), "recognized_parameters": ("table",), "structured_parameters": ("table",), "exclusive_parameter_groups": ()},
    TRAIT_PUBLICATION: {"locations": ("graph", "symbol"), "recognized_parameters": ("publication",), "structured_parameters": ("publication",), "exclusive_parameter_groups": ()},
    TRAIT_RUNTIME: {"locations": ("graph",), "recognized_parameters": ("configuration",), "structured_parameters": ("configuration",), "exclusive_parameter_groups": ()},
    TRAIT_BENCHMARK: {"locations": ("graph", "symbol"), "recognized_parameters": ("benchmark_id", "revision", "split", "configuration"), "structured_parameters": ("configuration",), "exclusive_parameter_groups": ()},
    TRAIT_DATASET: {"locations": ("graph", "symbol"), "recognized_parameters": ("dataset_id", "revision", "split", "configuration"), "structured_parameters": ("configuration",), "exclusive_parameter_groups": ()},
    TRAIT_METRIC: {"locations": ("graph", "symbol"), "recognized_parameters": ("measurement", "derived_metric"), "structured_parameters": ("measurement", "derived_metric"), "exclusive_parameter_groups": (("measurement", "derived_metric"),)},
    TRAIT_CONFIGURATION: {"locations": ("graph", "symbol"), "recognized_parameters": ("configuration",), "structured_parameters": ("configuration",), "exclusive_parameter_groups": ()},
    TRAIT_MODEL: {"locations": ("graph", "symbol"), "recognized_parameters": ("model_id", "revision", "capabilities", "context", "configuration"), "structured_parameters": ("configuration",), "exclusive_parameter_groups": ()},
    TRAIT_ENVIRONMENT: {"locations": ("graph", "symbol"), "recognized_parameters": ("environment_id", "family", "revision", "capabilities", "configuration"), "structured_parameters": ("configuration",), "exclusive_parameter_groups": ()},
    TRAIT_PARTICIPANT: {"locations": ("graph", "symbol"), "recognized_parameters": ("participant_id", "role", "capabilities", "configuration"), "structured_parameters": ("configuration",), "exclusive_parameter_groups": ()},
    TRAIT_PROTOCOL: {"locations": ("graph", "symbol"), "recognized_parameters": ("study", "protocol_id", "configuration"), "structured_parameters": ("study", "configuration"), "exclusive_parameter_groups": ()},
    TRAIT_TRIAL_PROVIDER: {"locations": ("symbol",), "recognized_parameters": ("provider_id", "configuration"), "structured_parameters": ("configuration",), "exclusive_parameter_groups": ()},
    TRAIT_VERIFIER: {"locations": ("graph", "symbol"), "recognized_parameters": ("verifier_id", "configuration"), "structured_parameters": ("configuration",), "exclusive_parameter_groups": ()},
    TRAIT_UNIT_ACTIVATION: {"locations": ("graph", "symbol"), "recognized_parameters": ("machine_id", "configuration"), "structured_parameters": ("configuration",), "exclusive_parameter_groups": ()},
    TRAIT_HYPOTHESIS: {"locations": ("graph", "symbol"), "recognized_parameters": ("statement", "variables", "direction", "scope"), "structured_parameters": (), "exclusive_parameter_groups": ()},
    TRAIT_CLAIM: {"locations": ("graph", "symbol"), "recognized_parameters": ("statement", "estimand", "evidence", "scope"), "structured_parameters": (), "exclusive_parameter_groups": ()},
    TRAIT_FACTOR: {"locations": ("graph", "symbol"), "recognized_parameters": ("levels", "assignment", "scope"), "structured_parameters": ("assignment",), "exclusive_parameter_groups": ()},
    TRAIT_TREATMENT: {"locations": ("graph", "symbol"), "recognized_parameters": ("factors", "interventions", "configuration"), "structured_parameters": ("configuration",), "exclusive_parameter_groups": ()},
    TRAIT_INTERVENTION: {"locations": ("graph", "symbol"), "recognized_parameters": ("target", "value", "policy", "scope"), "structured_parameters": (), "exclusive_parameter_groups": ()},
    TRAIT_COHORT: {"locations": ("graph", "symbol"), "recognized_parameters": ("population", "inclusion", "exclusion", "strata"), "structured_parameters": (), "exclusive_parameter_groups": ()},
    TRAIT_TASK: {"locations": ("graph", "symbol"), "recognized_parameters": ("task_id", "family", "schema", "content", "difficulty"), "structured_parameters": (), "exclusive_parameter_groups": ()},
    TRAIT_SPLIT: {"locations": ("graph", "symbol"), "recognized_parameters": ("split_id", "members", "policy"), "structured_parameters": (), "exclusive_parameter_groups": ()},
    TRAIT_MEASUREMENT: {"locations": ("graph", "symbol"), "recognized_parameters": ("measurement_id", "value_kind", "semantic_kind", "unit", "scale", "source_path", "reducer"), "structured_parameters": (), "exclusive_parameter_groups": ()},
    TRAIT_ARTIFACT: {"locations": ("graph", "symbol"), "recognized_parameters": ("artifact_id", "schema", "format", "lineage"), "structured_parameters": (), "exclusive_parameter_groups": ()},
    TRAIT_EVIDENCE: {"locations": ("graph", "symbol"), "recognized_parameters": ("evidence_id", "claim", "source", "lineage"), "structured_parameters": (), "exclusive_parameter_groups": ()},
    TRAIT_REPORT: {"locations": ("graph", "symbol"), "recognized_parameters": ("report_id", "sections", "artifacts"), "structured_parameters": (), "exclusive_parameter_groups": ()},
    TRAIT_OBJECTIVE: {"locations": ("graph", "symbol"), "recognized_parameters": ("metric", "direction", "constraints", "weights"), "structured_parameters": (), "exclusive_parameter_groups": ()},
    TRAIT_LOOP_PROGRESS: {"locations": ("graph", "symbol"), "recognized_parameters": ("progress",), "structured_parameters": (), "exclusive_parameter_groups": ()},
}


@dataclass(frozen=True, slots=True)
class ResearchTraitContract:
    trait_id: str
    locations: tuple[str, ...]
    recognized_parameters: tuple[str, ...]
    structured_parameters: tuple[str, ...]
    exclusive_parameter_groups: tuple[tuple[str, ...], ...]


BUILTIN_RESEARCH_TRAIT_CONTRACTS = MappingProxyType({
    trait_id: ResearchTraitContract(trait_id, **spec)
    for trait_id, spec in _TRAIT_CONTRACT_SPEC.items()
})


def validate_builtin_trait_authoring(
    trait_ids: tuple[str, ...],
    *,
    location: str,
    parameters: object,
) -> None:
    """Fail closed only for canonical semantics Noetrium itself interprets.

    Parameter dictionaries intentionally remain open to paper-specific fields.
    This validator enforces placement and structural invariants that would
    otherwise fail later during lowering with poorer diagnostics.
    """
    if location not in {"graph", "symbol"}:
        raise ValueError("research trait authoring location is invalid")
    mapping: Mapping[str, object]
    if parameters is None:
        mapping = {}
    elif isinstance(parameters, Mapping):
        mapping = parameters
    else:
        raise TypeError("research semantic parameters must be a mapping")
    for trait_id in trait_ids:
        contract = BUILTIN_RESEARCH_TRAIT_CONTRACTS.get(trait_id)
        if contract is None:
            if trait_id.startswith("research."):
                raise ValueError(
                    f"unknown canonical research trait {trait_id!r}; "
                    "the research.* namespace is reserved by Noetrium, so "
                    "paper-specific semantics must use a non-reserved namespace"
                )
            continue
        if location not in contract.locations:
            raise ValueError(
                f"{trait_id} cannot be authored on a {location}; "
                f"valid locations={contract.locations}"
            )
        for key in contract.structured_parameters:
            value = mapping.get(key)
            if value is not None and not isinstance(value, Mapping):
                raise TypeError(
                    f"{trait_id} parameters.{key} must be a mapping"
                )
        for group in contract.exclusive_parameter_groups:
            present = tuple(key for key in group if mapping.get(key) is not None)
            if len(present) > 1:
                raise ValueError(
                    f"{trait_id} parameters are mutually exclusive: {present}"
                )


__all__ = [
    "BUILTIN_RESEARCH_TRAIT_CONTRACTS",
    "ORGANIZATIONAL_TRAITS",
    "PLATFORM_BINDING_TRAITS",
    "SCIENTIFIC_METADATA_TRAITS",
    "ResearchTraitContract",
    "validate_builtin_trait_authoring",
    "validate_research_graph_semantics",
    "RELATION_FLOW",
] + [name for name in globals() if name.startswith("TRAIT_")]


_VALIDATED_RESEARCH_SUBTREES: OrderedDict[str, None] = OrderedDict()
_VALIDATED_RESEARCH_SUBTREES_LOCK = RLock()
_VALIDATED_RESEARCH_SUBTREES_LIMIT = 262_144


def validate_research_graph_semantics(root: NoetriumUnit) -> None:
    """Validate Research semantics with Merkle-pruned hypergraph traversal."""
    if type(root) is not NoetriumUnit:
        raise TypeError("research schema validation requires NoetriumUnit")
    stack: list[tuple[NoetriumUnit, bool]] = [(root, False)]
    while stack:
        graph, exiting = stack.pop()
        digest = graph.semantic_digest
        if exiting:
            with _VALIDATED_RESEARCH_SUBTREES_LOCK:
                _VALIDATED_RESEARCH_SUBTREES[digest] = None
                _VALIDATED_RESEARCH_SUBTREES.move_to_end(digest)
                while len(_VALIDATED_RESEARCH_SUBTREES) > _VALIDATED_RESEARCH_SUBTREES_LIMIT:
                    _VALIDATED_RESEARCH_SUBTREES.popitem(last=False)
            continue
        with _VALIDATED_RESEARCH_SUBTREES_LOCK:
            if digest in _VALIDATED_RESEARCH_SUBTREES:
                _VALIDATED_RESEARCH_SUBTREES.move_to_end(digest)
                continue

        stack.append((graph, True))
        children = {child.unit_id: child for child in graph.members}
        incoming: dict[tuple[str | None, str | None], int] = {}
        adjacency: dict[tuple[str, object], list[tuple[str, object]]] = {
            ("member", child_id): [] for child_id in children
        }
        relation_ordinal = 0

        for relation in graph.relations:
            sources = relation.units("source")
            targets = relation.units("target")
            kind = relation_id(relation)
            if kind == RELATION_FLOW:
                relation_node = ("relation", relation_ordinal)
                relation_ordinal += 1
                adjacency[relation_node] = []

                for endpoint in targets:
                    target_id = endpoint_child_id(endpoint)
                    target_port = endpoint_port_name(endpoint)
                    key = (target_id, target_port)
                    incoming[key] = incoming.get(key, 0) + 1
                    if target_id is not None:
                        if target_id not in children:
                            raise ValueError("research flow references unknown target child")
                        target_node = ("member", target_id)
                        adjacency[relation_node].append(target_node)

                for endpoint in sources:
                    source_id = endpoint_child_id(endpoint)
                    if source_id is not None:
                        if source_id not in children:
                            raise ValueError("research flow references unknown source child")
                        source_node = ("member", source_id)
                        adjacency[source_node].append(relation_node)
                continue

            if kind.startswith("research."):
                endpoints = sources + targets
                if any(endpoint_child_id(endpoint) is None for endpoint in endpoints):
                    raise ValueError("scientific research relation must connect child graphs")
                if any(endpoint_port_name(endpoint) is not None for endpoint in endpoints):
                    raise ValueError("scientific research relation cannot bind execution ports")

        for child in graph.members:
            for port in child.boundary.units("input"):
                count = incoming.get((child.unit_id, port.unit_id), 0)
                if port_mode(port) is GraphPortMode.ONE and count != 1:
                    raise ValueError(
                        f"research graph {child.unit_id!r} input {port.unit_id!r} "
                        "requires exactly one incoming flow"
                    )
                if port_mode(port) is GraphPortMode.OPTIONAL and count > 1:
                    raise ValueError(
                        f"research graph {child.unit_id!r} optional input "
                        f"{port.unit_id!r} accepts at most one incoming flow"
                    )
        for port in graph.boundary.units("output"):
            count = incoming.get((None, port.unit_id), 0)
            if port_mode(port) in {GraphPortMode.ONE, GraphPortMode.OPTIONAL} and count > 1:
                raise ValueError(
                    f"research graph output {port.unit_id!r} accepts at most one internal producer"
                )

        for component in strongly_connected_components(
            tuple(adjacency),
            adjacency,
        ):
            cyclic = len(component) > 1 or any(
                node in adjacency[node] for node in component
            )
            if not cyclic:
                continue
            component_children = tuple(
                str(value) for kind, value in component if kind == "member"
            )
            if component_children and not any(
                children[child_id].boundary.units("state")
                or children[child_id].boundary.units("effect")
                or children[child_id].has_trait(TRAIT_LOOP_PROGRESS)
                for child_id in component_children
            ):
                raise ValueError(
                    "research execution cycle has no state/effect/progress source: "
                    + ", ".join(sorted(component_children))
                )

        stack.extend((child, False) for child in reversed(graph.members))

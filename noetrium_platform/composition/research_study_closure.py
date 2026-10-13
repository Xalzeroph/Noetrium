from __future__ import annotations
from noetrium_platform.foundation.kernel.structure import NoetriumUnit

from collections.abc import Mapping

from noetrium_platform.foundation.kernel.kernel import thaw_json
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.product.research_traits import TRAIT_METRIC, TRAIT_PROTOCOL
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import (
    measurement_definitions,
    measurement_id,
    measurement_protocol_unit,
    measurement_unit,
    require_study_unit,
    study_measurement_protocol,
    study_unit_from_spec,
    StudySpecCompiler,
    study_with_measurement_protocol,
)

from .research_binding_authority import (
    ResearchBindingAuthorityPort,
)
from .research_symbol_authority import (
    ResearchSymbolBindingAuthorityPort,
)
from .research_execution_graph import ResearchExecutionBinding
from noetrium_platform.research.experimentation.api import (
    ResearchBindingContribution,
    compile_experiment_program,
    compile_research_plan,
    research_plan_study,
)
from .research_lowering import (
    ImportResearchImplementationResolver,
    ResearchImplementationResolverPort,
)


def _measurement_authoring_mapping(
    row: NoetriumUnit,
) -> dict[str, object]:
    params = row.parameters
    return {
        "measurement_id": measurement_id(row),
        "schema_id": str(params["schema_id"]),
        "value_kind": str(params["value_kind"]),
        "unit": params.get("unit"),
        "description": str(params.get("description", "")),
        "semantic_kind": str(params.get("semantic_kind", "measurement")),
        "scale": params.get("scale"),
        "domain": params.get("domain"),
        "source_path": params.get("source_path"),
        "reducer": params.get("reducer"),
    }

def materialize_platform_research_protocol_binding(
    definition: NoetriumUnit,
    *,
    declared_measurements: tuple[NoetriumUnit, ...] = (),
    compiler: StudySpecCompiler | None = None,
) -> NoetriumUnit:
    """Materialize one declarative platform-owned Study for binding creation.

    This seam is used only while constructing the exact definition-binding
    authority. Runtime protocol consumers still resolve platform-owned
    definitions through that authority.
    """

    if type(definition) is not NoetriumUnit:
        raise TypeError(
            "platform protocol binding materialization requires NoetriumUnit"
        )
    if not definition.has_trait(TRAIT_PROTOCOL):
        raise TypeError(
            "platform protocol binding materialization requires research.protocol symbol"
        )
    if not definition.platform_resolved or definition.implementation is not None:
        raise ValueError(
            "platform protocol binding materialization requires declarative "
            "platform-resolved definition"
        )
    config = thaw_json(definition.parameters)
    if not isinstance(config, Mapping):
        raise TypeError(
            "platform-resolved PROTOCOL requires declarative study config"
        )
    candidate = config.get("study", config)
    if not isinstance(candidate, Mapping):
        raise TypeError(
            "platform-resolved PROTOCOL study config must be an object"
        )
    authored = dict(candidate)
    if not authored.get("measurements") and declared_measurements:
        authored["measurements"] = tuple(
            _measurement_authoring_mapping(row)
            for row in declared_measurements
        )
    return study_unit_from_spec(authored, compiler=compiler)


def materialize_research_protocol_definition(
    definition,
    resolver: ResearchImplementationResolverPort | None = None,
    symbol_bindings: ResearchSymbolBindingAuthorityPort | None = None,
    declared_measurements: tuple[NoetriumUnit, ...] = (),
    compiler: StudySpecCompiler | None = None,
) -> NoetriumUnit:
    if not definition.has_trait(TRAIT_PROTOCOL):
        raise TypeError(
            "research protocol materialization requires research.protocol symbol"
        )
    if definition.implementation is None:
        if symbol_bindings is None:
            raise RuntimeError(
                "platform-resolved PROTOCOL requires definition binding authority"
            )
        binding = symbol_bindings.resolve(
            definition,
            owner_trait_id=TRAIT_PROTOCOL,
        )
        study = binding.binding
        return require_study_unit(study)
    selected = ImportResearchImplementationResolver() if resolver is None else resolver
    resolved = selected.resolve(definition)
    try:
        study = resolved.implementation()
    except Exception as exc:
        raise RuntimeError("Research Study protocol factory failed: " + f"{resolved.declared.module}:{resolved.declared.qualname}") from exc
    if type(study) is NoetriumUnit:
        return require_study_unit(study)
    if isinstance(study, dict):
        authored = dict(study)
        if not authored.get("measurements") and declared_measurements:
            authored["measurements"] = tuple(
                _measurement_authoring_mapping(row)
                for row in declared_measurements
            )
        return study_unit_from_spec(authored, compiler=compiler)
    raise TypeError("Research Study protocol factory must return a top-level Study mapping")


def research_measurement_definitions(
    definitions: tuple[NoetriumUnit, ...],
) -> tuple[NoetriumUnit, ...]:
    """Project top-level METRIC definitions into Unit measurement semantics."""

    rows: list[NoetriumUnit] = []
    for definition in definitions:
        if not definition.has_trait(TRAIT_METRIC):
            continue
        config = definition.parameters
        if not isinstance(config, Mapping):
            continue
        raw = config.get("measurement")
        if raw is None:
            continue
        if not isinstance(raw, Mapping):
            raise TypeError("research metric measurement spec must be an object")
        rows.append(
            measurement_unit(
                str(raw["measurement_id"]),
                schema_id=str(raw["schema_id"]),
                value_kind=str(raw["value_kind"]),
                unit=None if raw.get("unit") is None else str(raw["unit"]),
                description=str(raw.get("description", "")),
                semantic_kind=str(raw.get("semantic_kind", definition.unit_id)),
                scale=None if raw.get("scale") is None else str(raw["scale"]),
                domain=None if raw.get("domain") is None else str(raw["domain"]),
                source_path=None if raw.get("source_path") is None else str(raw["source_path"]),
                reducer=None if raw.get("reducer") is None else str(raw["reducer"]),
            )
        )
    ordered = tuple(sorted(rows, key=measurement_id))
    ids = tuple(measurement_id(row) for row in ordered)
    if len(ids) != len(set(ids)):
        raise ValueError("top-level metric declarations duplicate measurement ids")
    return ordered

def merge_research_measurements(
    study: NoetriumUnit,
    definitions: tuple[NoetriumUnit, ...],
) -> NoetriumUnit:
    study = require_study_unit(study)
    declared = research_measurement_definitions(definitions)
    if not declared:
        return study
    current_protocol = study_measurement_protocol(study)
    existing = {measurement_id(row): row for row in measurement_definitions(current_protocol)}
    changed = False
    for row in declared:
        key = measurement_id(row)
        current = existing.get(key)
        if current is not None and current != row:
            raise ValueError(
                "top-level metric measurement conflicts with protocol measurement: "
                f"{key}"
            )
        if current is None:
            existing[key] = row
            changed = True
    if not changed:
        return study
    protocol = measurement_protocol_unit(
        current_protocol.unit_id,
        tuple(sorted(existing.values(), key=measurement_id)),
        schema_version=str(current_protocol.parameters["schema_version"]),
    )
    return study_with_measurement_protocol(study, protocol)

class ResearchExperimentCompilationProvider:
    """Compile generic Experiment nodes directly into Unit-native execution inputs."""

    def __init__(
        self,
        research_bindings: ResearchBindingAuthorityPort,
        resolver: ResearchImplementationResolverPort | None = None,
        symbol_bindings: ResearchSymbolBindingAuthorityPort | None = None,
        pre_materialized_studies: Mapping[str, NoetriumUnit] | None = None,
        precompiled_experiments: Mapping[
            str,
            tuple[
                NoetriumUnit,
                ResearchBindingContribution,
                NoetriumUnit,
                NoetriumUnit,
            ],
        ] | None = None,
    ) -> None:
        if not isinstance(research_bindings, ResearchBindingAuthorityPort):
            raise TypeError(
                "Study closure provider requires ResearchBindingAuthorityPort"
            )
        resolved = (
            ImportResearchImplementationResolver()
            if resolver is None
            else resolver
        )
        if not isinstance(resolved, ResearchImplementationResolverPort):
            raise TypeError(
                "Study closure provider resolver must satisfy "
                "ResearchImplementationResolverPort"
            )
        self._research_bindings = research_bindings
        self._resolver = resolved
        if symbol_bindings is not None and not isinstance(
            symbol_bindings,
            ResearchSymbolBindingAuthorityPort,
        ):
            raise TypeError(
                "Study closure symbol_bindings must satisfy typed port"
            )
        self._symbol_bindings = symbol_bindings
        cached_studies = {} if pre_materialized_studies is None else dict(pre_materialized_studies)
        for protocol_digest, study in cached_studies.items():
            if type(protocol_digest) is not str or not protocol_digest.strip():
                raise ValueError("pre-materialized protocol digest must be non-empty text")
            cached_studies[protocol_digest] = require_study_unit(study)
        self._pre_materialized_studies = cached_studies
        cached_compilations = (
            {} if precompiled_experiments is None else dict(precompiled_experiments)
        )
        for protocol_digest, closure in cached_compilations.items():
            if type(protocol_digest) is not str or not protocol_digest.strip():
                raise ValueError(
                    "precompiled Experiment protocol digest must be non-empty text"
                )
            if type(closure) is not tuple or len(closure) != 4:
                raise TypeError(
                    "precompiled Experiment closure must be "
                    "(Study, binding, plan, program)"
                )
            study, binding, plan, program = closure
            cached_compilations[protocol_digest] = (
                require_study_unit(study),
                binding,
                plan,
                program,
            )
            if type(binding) is not ResearchBindingContribution:
                raise TypeError(
                    "precompiled Experiment closure binding must be "
                    "ResearchBindingContribution"
                )
            if type(plan) is not NoetriumUnit or type(program) is not NoetriumUnit:
                raise TypeError(
                    "precompiled Experiment closure plan/program must be NoetriumUnit"
                )
        self._precompiled_experiments = cached_compilations

    def _study(self, node: ResearchExecutionBinding) -> NoetriumUnit:
        candidates = tuple(
            row
            for row in node.symbols
            if row.has_trait(TRAIT_PROTOCOL)
        )
        if len(candidates) != 1:
            raise ValueError(
                "Experiment node requires exactly one PROTOCOL definition: "
                f"node={node.graph_node_id} count={len(candidates)}"
            )
        definition = candidates[0]
        declared = research_measurement_definitions(node.symbols)
        study = self._pre_materialized_studies.get(definition.symbol_digest)
        if study is None:
            study = materialize_research_protocol_definition(
                definition,
                self._resolver,
                self._symbol_bindings,
                declared,
            )
        elif definition.implementation is None:
            if self._symbol_bindings is None:
                raise RuntimeError(
                    "cached platform-resolved PROTOCOL requires definition binding authority"
                )
            binding = self._symbol_bindings.resolve(
                definition,
                owner_trait_id=TRAIT_PROTOCOL,
            )
            binding.validate_symbol(definition)
            bound_study = require_study_unit(binding.binding)
            if bound_study.unit_digest != study.unit_digest:
                raise ValueError(
                    "pre-materialized Study drifted from authoritative PROTOCOL binding"
                )
        return merge_research_measurements(study,node.symbols)

    def resolve(
        self,
        node: ResearchExecutionBinding,
    ) -> tuple[
        NoetriumUnit,
        ResearchBindingContribution,
        NoetriumUnit,
        NoetriumUnit,
    ]:
        if type(node) is not ResearchExecutionBinding:
            raise TypeError(
                "Study closure provider requires ResearchExecutionBinding"
            )
        protocol_definitions = tuple(
            row for row in node.symbols if row.has_trait(TRAIT_PROTOCOL)
        )
        if len(protocol_definitions) != 1:
            raise ValueError(
                "Experiment node requires exactly one PROTOCOL definition: "
                f"node={node.graph_node_id} count={len(protocol_definitions)}"
            )
        protocol_definition = protocol_definitions[0]
        study = self._study(node)
        precompiled = self._precompiled_experiments.get(
            protocol_definition.symbol_digest
        )
        if precompiled is not None:
            frozen_study, binding, plan, program = precompiled
            if frozen_study.unit_digest != study.unit_digest:
                raise ValueError(
                    "precompiled Experiment Study drifted from authoritative Study"
                )
            if not binding.binding_assurance_complete:
                raise RuntimeError(
                    "Study binding assurance is incomplete; scientific execution "
                    "requires all required bindings to be proof-backed: "
                    + ",".join(row.gap_digest for row in binding.assurance_gaps)
                )
            return study, binding, plan, program

        resolved = self._research_bindings.resolve(study)
        if type(resolved) is not tuple or len(resolved) != 2:
            raise TypeError(
                "research binding authority must return "
                "(ResearchRequirementResolution, ResearchBindingContribution)"
            )
        resolution, binding = resolved
        if not binding.binding_assurance_complete:
            raise RuntimeError(
                "Study binding assurance is incomplete; scientific execution "
                "requires all required bindings to be proof-backed: "
                + ",".join(row.gap_digest for row in binding.assurance_gaps)
            )
        plan = compile_research_plan(study, resolution, binding)
        program = compile_experiment_program(research_plan_study(plan))
        return study, binding, plan, program


__all__ = [
    "ResearchExperimentCompilationProvider",
    "StudySpecCompiler",
    "materialize_research_protocol_definition",
    "merge_research_measurements",
    "research_measurement_definitions",
]

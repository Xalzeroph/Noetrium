"""Canonical compiler from reproduction declarations into the Research OS surface.

Reproduction packages own scientific semantics in their typed MethodProgram,
Study, benchmark and fidelity assets.  This module owns no paper-specific
semantics; it only proves those declared assets can be represented by the
current top-level ResearchProgram/ResearchPortfolio model.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum, StrEnum
import importlib
import inspect
from itertools import product
from pathlib import Path, PurePosixPath
from typing import Protocol, get_type_hints, runtime_checkable

from noetrium import api
from noetrium_platform.capabilities.participant.capability.api.selection import (
    CapabilitySelectionView,
)
from noetrium_platform.foundation.kernel.kernel import (
    JsonValue,
    canonical_digest,
    freeze_json,
)
from noetrium_platform.research.execution.machines.api import (
    ResearchProgram as MachineResearchProgram,
)
from noetrium_platform.research.execution.workflow.api import MethodProgram
from noetrium_platform.research.experimentation.lifecycle.api import (
    BenchmarkTaskSet,
    ResearchStudyDefinition,
)

from .contracts import (
    ReproductionAssetKind,
    ReproductionAssetRef,
    ReproductionDefinition,
    ReproductionLifecycle,
    ReproductionMethodProgramFactoryBinding,
)


class ReproductionResearchOSCompileError(RuntimeError):
    pass


class ReproductionExecutionRequirementKind(StrEnum):
    """Typed non-benchmark input required to close one reproduction execution."""

    CAPABILITY_ID = "capability_id"
    CAPABILITY_CLOSURE = "capability_closure"
    PAPER_OPTION = "paper_option"


@dataclass(frozen=True, slots=True)
class ReproductionExecutionRequirement:
    """One exact closure-time input; values are supplied by execution composition."""

    package: str
    parameter: str
    kind: ReproductionExecutionRequirementKind
    consumers: tuple[str, ...]
    requirement_digest: str

    def __post_init__(self) -> None:
        if type(self.package) is not str or not self.package.strip():
            raise ValueError("reproduction execution requirement package is required")
        if type(self.parameter) is not str or not self.parameter.strip():
            raise ValueError("reproduction execution requirement parameter is required")
        if not isinstance(self.kind, ReproductionExecutionRequirementKind):
            raise TypeError("reproduction execution requirement kind must be typed")
        if type(self.consumers) is not tuple or not self.consumers:
            raise ValueError("reproduction execution requirement needs consumers")
        consumers = tuple(sorted(self.consumers))
        if (
            consumers != self.consumers
            or len(consumers) != len(set(consumers))
            or any(type(row) is not str or not row.strip() for row in consumers)
        ):
            raise ValueError(
                "reproduction execution requirement consumers must be unique canonical text"
            )
        if (
            type(self.requirement_digest) is not str
            or len(self.requirement_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in self.requirement_digest)
        ):
            raise ValueError(
                "reproduction execution requirement digest must be lowercase SHA-256"
            )


@runtime_checkable
class ReproductionCapabilityRequirementResolverPort(Protocol):
    """Resolve one semantic capability requirement from authoritative platform state.

    Implementations own no capability definitions. They return a pinned
    CapabilitySelectionView materialized from the real capability authority.
    """

    def resolve(
        self,
        requirement: ReproductionExecutionRequirement,
    ) -> CapabilitySelectionView: ...


@dataclass(frozen=True, slots=True)
class ReproductionExecutionResolution:
    """One exact non-benchmark closure variant before benchmark lane expansion."""

    package: str
    study_factory: str
    values: Mapping[str, JsonValue]
    proof_digests: tuple[str, ...]
    resolution_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.package) is not str or not self.package.strip():
            raise ValueError("reproduction resolution package is required")
        if type(self.study_factory) is not str or not self.study_factory.strip():
            raise ValueError("reproduction resolution study_factory is required")
        if not isinstance(self.values, Mapping):
            raise TypeError("reproduction resolution values must be a mapping")
        frozen_values = freeze_json({
            key: self.values[key]
            for key in sorted(self.values)
        })
        if not isinstance(frozen_values, Mapping):
            raise TypeError("reproduction resolution values must freeze to object")
        if type(self.proof_digests) is not tuple:
            raise TypeError("reproduction resolution proof_digests must be tuple")
        proofs = tuple(sorted(self.proof_digests))
        if len(proofs) != len(set(proofs)) or any(
            type(value) is not str
            or len(value) != 64
            or any(ch not in "0123456789abcdef" for ch in value)
            for value in proofs
        ):
            raise ValueError(
                "reproduction resolution proofs must be unique SHA-256 digests"
            )
        object.__setattr__(self, "values", frozen_values)
        object.__setattr__(self, "proof_digests", proofs)
        object.__setattr__(
            self,
            "resolution_digest",
            canonical_digest({
                "package": self.package,
                "study_factory": self.study_factory,
                "values": frozen_values,
                "proof_digests": proofs,
            }),
        )


@dataclass(frozen=True, slots=True)
class ReproductionExecutionRequest:
    """Top-level request selecting scientific lane identity, never platform wiring."""

    package: str
    study_factory: str
    benchmark: BenchmarkTaskSet

    def __post_init__(self) -> None:
        if type(self.package) is not str or not self.package.strip():
            raise ValueError("reproduction execution request package is required")
        if type(self.study_factory) is not str or not self.study_factory.strip():
            raise ValueError("reproduction execution request study_factory is required")
        if not isinstance(self.benchmark, BenchmarkTaskSet):
            raise TypeError(
                "reproduction execution request benchmark must be BenchmarkTaskSet"
            )

    @property
    def request_digest(self) -> str:
        return canonical_digest({
            "package": self.package,
            "study_factory": self.study_factory,
            "benchmark_id": self.benchmark.benchmark_id,
            "benchmark_revision_id": self.benchmark.revision_id,
            "benchmark_cut_digest": self.benchmark.cut_digest,
        })


_BENCHMARK_SPLIT_PARAMETERS = frozenset({"split_id", "benchmark_split_id"})

_EXECUTION_REQUIREMENT_KIND_BY_PARAMETER = {
    "search_capability_id": ReproductionExecutionRequirementKind.CAPABILITY_ID,
    "expert_capability_ids": ReproductionExecutionRequirementKind.CAPABILITY_CLOSURE,
    "tool_capability_ids": ReproductionExecutionRequirementKind.CAPABILITY_CLOSURE,
    "capability_ids": ReproductionExecutionRequirementKind.CAPABILITY_CLOSURE,
    "interpretation": ReproductionExecutionRequirementKind.PAPER_OPTION,
    "sampling_frame_number": ReproductionExecutionRequirementKind.PAPER_OPTION,
}


@dataclass(frozen=True, slots=True)
class ReproductionExecutionBinding:
    """Exact values selecting one executable reproduction lane."""

    package: str
    binding_id: str
    study_factory: str
    benchmark_id: str
    benchmark_split_id: str | None
    values: Mapping[str, JsonValue]
    requirement_digests: tuple[str, ...]
    resolution_proof_digests: tuple[str, ...] = ()
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name, value in (
            ("package", self.package),
            ("binding_id", self.binding_id),
            ("study_factory", self.study_factory),
            ("benchmark_id", self.benchmark_id),
        ):
            if type(value) is not str or not value.strip() or value != value.strip():
                raise ValueError(
                    f"reproduction execution binding {field_name} must be canonical text"
                )
        if self.benchmark_split_id is not None and (
            type(self.benchmark_split_id) is not str
            or not self.benchmark_split_id.strip()
            or self.benchmark_split_id != self.benchmark_split_id.strip()
        ):
            raise ValueError(
                "reproduction execution binding benchmark_split_id must be canonical text"
            )
        if not isinstance(self.values, Mapping):
            raise TypeError("reproduction execution binding values must be a mapping")
        frozen_values = freeze_json(
            {
                key: self.values[key]
                for key in sorted(self.values)
            }
        )
        if not isinstance(frozen_values, Mapping):
            raise TypeError("reproduction execution binding values must freeze to object")
        if type(self.requirement_digests) is not tuple:
            raise TypeError(
                "reproduction execution binding requirement_digests must be tuple"
            )
        digests = tuple(sorted(self.requirement_digests))
        if len(digests) != len(set(digests)) or any(
            type(value) is not str
            or len(value) != 64
            or any(ch not in "0123456789abcdef" for ch in value)
            for value in digests
        ):
            raise ValueError(
                "reproduction execution binding requirement digests must be unique SHA-256"
            )
        if type(self.resolution_proof_digests) is not tuple:
            raise TypeError(
                "reproduction execution binding resolution_proof_digests must be tuple"
            )
        resolution_proofs = tuple(sorted(self.resolution_proof_digests))
        if len(resolution_proofs) != len(set(resolution_proofs)) or any(
            type(value) is not str
            or len(value) != 64
            or any(ch not in "0123456789abcdef" for ch in value)
            for value in resolution_proofs
        ):
            raise ValueError(
                "reproduction execution resolution proofs must be unique SHA-256"
            )
        object.__setattr__(self, "values", frozen_values)
        object.__setattr__(self, "requirement_digests", digests)
        object.__setattr__(
            self,
            "resolution_proof_digests",
            resolution_proofs,
        )
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest(
                {
                    "package": self.package,
                    "binding_id": self.binding_id,
                    "study_factory": self.study_factory,
                    "benchmark_id": self.benchmark_id,
                    "benchmark_split_id": self.benchmark_split_id,
                    "values": frozen_values,
                    "requirement_digests": digests,
                    "resolution_proof_digests": resolution_proofs,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ReproductionMachineProgramBinding:
    """Exact immutable Research Machine program declared by a reproduction asset."""

    package: str
    asset: ReproductionAssetRef
    module: str
    qualname: str
    program_id: str
    machine_kind: str
    program_digest: str

    def __post_init__(self) -> None:
        if not self.package:
            raise ValueError("reproduction machine binding package is required")
        if self.asset.kind is not ReproductionAssetKind.RESEARCH_PROGRAM:
            raise ValueError("reproduction machine binding asset kind drifted")
        if not self.module or not self.qualname or not self.program_id:
            raise ValueError("reproduction machine binding identity is incomplete")
        if not self.machine_kind:
            raise ValueError("reproduction machine binding kind is required")
        if len(self.program_digest) != 64:
            raise ValueError("reproduction machine program digest must be SHA-256 text")


@dataclass(frozen=True, slots=True)
class ReproductionStudyFactoryBinding:
    """Package-local typed Study factory consumed by ExperimentClosure compilation."""

    package: str
    asset: ReproductionAssetRef
    module: str
    qualname: str
    benchmark_parameter: str
    parameter_names: tuple[str, ...]
    required_parameters: tuple[str, ...]
    binding_digest: str

    def __post_init__(self) -> None:
        if not self.package or not self.module or not self.qualname:
            raise ValueError("reproduction Study factory identity is incomplete")
        if self.asset.kind is not ReproductionAssetKind.STUDY:
            raise ValueError("reproduction Study factory asset kind drifted")
        if self.benchmark_parameter not in self.parameter_names:
            raise ValueError("reproduction Study factory lost benchmark parameter")
        if tuple(sorted(set(self.parameter_names))) != tuple(sorted(self.parameter_names)):
            raise ValueError("reproduction Study factory parameters must be unique")
        if any(name not in self.parameter_names for name in self.required_parameters):
            raise ValueError("reproduction Study factory required parameters drifted")
        if len(self.binding_digest) != 64:
            raise ValueError("reproduction Study factory digest must be SHA-256 text")

    @property
    def benchmark_split_parameter(self) -> str | None:
        matches = tuple(
            name
            for name in self.required_parameters
            if name in _BENCHMARK_SPLIT_PARAMETERS
        )
        if len(matches) > 1:
            raise ReproductionResearchOSCompileError(
                f"{self.package} Study factory {self.qualname} declares multiple "
                f"benchmark split parameters: {matches}"
            )
        return None if not matches else matches[0]

    @property
    def unresolved_parameters(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in self.required_parameters
            if name != self.benchmark_parameter
            and name not in _BENCHMARK_SPLIT_PARAMETERS
        )

    @property
    def exact_after_benchmark(self) -> bool:
        return not self.unresolved_parameters


@dataclass(frozen=True, slots=True)
class ReproductionMethodProgramBinding:
    package: str
    asset: ReproductionAssetRef
    module: str
    qualname: str
    program_digest: str | None
    binding_kind: str = "symbol"
    factory: ReproductionMethodProgramFactoryBinding | None = None

    def __post_init__(self) -> None:
        if not self.package:
            raise ValueError("reproduction MethodProgram binding package is required")
        if self.asset.kind is not ReproductionAssetKind.METHOD_PROGRAM:
            raise ValueError("reproduction MethodProgram binding asset kind drifted")
        if not self.module or not self.qualname:
            raise ValueError("reproduction MethodProgram import coordinates are required")
        if self.binding_kind not in {"symbol", "factory"}:
            raise ValueError("reproduction MethodProgram binding kind is invalid")
        if self.binding_kind == "symbol":
            if self.factory is not None:
                raise ValueError("symbol MethodProgram binding cannot carry factory metadata")
            if type(self.program_digest) is not str or len(self.program_digest) != 64:
                raise ValueError("symbol MethodProgram digest must be SHA-256 text")
        else:
            if type(self.factory) is not ReproductionMethodProgramFactoryBinding:
                raise TypeError("factory MethodProgram binding requires typed factory")
            if self.qualname != self.factory.qualname:
                raise ValueError("factory MethodProgram qualname drifted")
            if self.factory.exact:
                if type(self.program_digest) is not str or len(self.program_digest) != 64:
                    raise ValueError("exact factory MethodProgram requires SHA-256 digest")
            elif self.program_digest is not None:
                raise ValueError(
                    "parameterized MethodProgram factory cannot claim a program digest"
                )

    @property
    def exact(self) -> bool:
        return self.program_digest is not None

    @property
    def binding_digest(self) -> str:
        if self.factory is not None:
            return self.factory.binding_digest
        assert self.program_digest is not None
        return self.program_digest


def _asset(
    definition: ReproductionDefinition,
    kind: ReproductionAssetKind,
) -> ReproductionAssetRef:
    rows = tuple(row for row in definition.assets if row.kind is kind)
    if len(rows) != 1:
        raise ReproductionResearchOSCompileError(
            f"{definition.package} requires exactly one {kind.value} asset; "
            f"found={len(rows)}"
        )
    return rows[0]


def _module_from_asset(
    definition: ReproductionDefinition,
    asset: ReproductionAssetRef,
) -> str:
    path = PurePosixPath(asset.path)
    expected_prefix = (
        "research",
        "reproductions",
        definition.package,
    )
    if path.suffix != ".py" or path.parts[:3] != expected_prefix:
        raise ReproductionResearchOSCompileError(
            f"{definition.package} asset is not package-local Python: {asset.path}"
        )
    return ".".join(path.with_suffix("").parts)


def _annotation_text(annotation: object) -> str:
    if annotation is inspect.Signature.empty:
        return ""
    if type(annotation) is str:
        return annotation
    return getattr(annotation, "__name__", str(annotation))


def resolve_study_factory_bindings(
    definition: ReproductionDefinition,
) -> tuple[ReproductionStudyFactoryBinding, ...]:
    """Resolve every explicit package-local Study factory without guessing."""

    if type(definition) is not ReproductionDefinition:
        raise TypeError("reproduction Study binding requires definition")
    asset = _asset(definition, ReproductionAssetKind.STUDY)
    module_name = _module_from_asset(definition, asset)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ReproductionResearchOSCompileError(
            f"{definition.package} Study module cannot be imported: {module_name}"
        ) from exc
    exported = getattr(module, "__all__", ())
    if type(exported) not in {list, tuple} or any(
        type(name) is not str or not name for name in exported
    ):
        raise ReproductionResearchOSCompileError(
            f"{definition.package} Study module __all__ must be explicit"
        )

    bindings: list[ReproductionStudyFactoryBinding] = []
    for name in exported:
        value = getattr(module, name, None)
        if not inspect.isfunction(value) or value.__module__ != module_name:
            continue
        try:
            signature = inspect.signature(value)
        except (TypeError, ValueError):
            continue
        if _annotation_text(signature.return_annotation) != "ResearchStudyDefinition":
            continue
        parameters = tuple(signature.parameters.values())
        benchmark_parameters = tuple(
            parameter.name
            for parameter in parameters
            if "BenchmarkTaskSet" in _annotation_text(parameter.annotation)
        )
        if len(benchmark_parameters) != 1:
            raise ReproductionResearchOSCompileError(
                f"{definition.package} Study factory {name} must declare exactly one "
                f"BenchmarkTaskSet parameter; found={benchmark_parameters}"
            )
        parameter_names = tuple(parameter.name for parameter in parameters)
        required_parameters = tuple(
            parameter.name
            for parameter in parameters
            if parameter.default is inspect.Parameter.empty
            and parameter.kind not in {
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            }
        )
        binding_digest = canonical_digest(
            {
                "package": definition.package,
                "asset_path": asset.path,
                "module": module_name,
                "qualname": name,
                "benchmark_parameter": benchmark_parameters[0],
                "parameter_names": parameter_names,
                "required_parameters": required_parameters,
            }
        )
        bindings.append(
            ReproductionStudyFactoryBinding(
                definition.package,
                asset,
                module_name,
                name,
                benchmark_parameters[0],
                parameter_names,
                required_parameters,
                binding_digest,
            )
        )
    if not bindings:
        raise ReproductionResearchOSCompileError(
            f"{definition.package} must export at least one package-local "
            "ResearchStudyDefinition factory"
        )
    return tuple(sorted(bindings, key=lambda row: (row.qualname, row.binding_digest)))


def resolve_benchmark_split_consumers(
    definition: ReproductionDefinition,
) -> tuple[str, ...]:
    """Return exact consumers of the platform-owned benchmark split axis."""

    if type(definition) is not ReproductionDefinition:
        raise TypeError("benchmark split consumers require reproduction definition")
    consumers: set[str] = set()
    for study in resolve_study_factory_bindings(definition):
        if study.benchmark_split_parameter is not None:
            consumers.add(f"study:{study.qualname}")

    method_assets = tuple(
        row
        for row in definition.assets
        if row.kind is ReproductionAssetKind.METHOD_PROGRAM
    )
    if method_assets:
        method = resolve_method_program_binding(definition)
        if method.factory is not None:
            if any(
                name in _BENCHMARK_SPLIT_PARAMETERS
                for name in method.factory.unresolved_parameters
            ):
                consumers.add(f"method:{method.qualname}")
    return tuple(sorted(consumers))


def resolve_execution_requirements(
    definition: ReproductionDefinition,
) -> tuple[ReproductionExecutionRequirement, ...]:
    """Compile all unresolved Study/Method inputs into a typed closure contract."""

    if type(definition) is not ReproductionDefinition:
        raise TypeError("reproduction execution requirements require definition")

    consumers: dict[str, set[str]] = {}
    for study in resolve_study_factory_bindings(definition):
        for parameter in study.unresolved_parameters:
            consumers.setdefault(parameter, set()).add(
                f"study:{study.qualname}"
            )

    method_assets = tuple(
        row
        for row in definition.assets
        if row.kind is ReproductionAssetKind.METHOD_PROGRAM
    )
    if method_assets:
        method = resolve_method_program_binding(definition)
        if not method.exact:
            assert method.factory is not None
            for parameter in method.factory.unresolved_parameters:
                if parameter in _BENCHMARK_SPLIT_PARAMETERS:
                    continue
                consumers.setdefault(parameter, set()).add(
                    f"method:{method.qualname}"
                )

    rows: list[ReproductionExecutionRequirement] = []
    for parameter in sorted(consumers):
        kind = _EXECUTION_REQUIREMENT_KIND_BY_PARAMETER.get(parameter)
        if kind is None:
            raise ReproductionResearchOSCompileError(
                f"{definition.package} has untyped execution parameter: {parameter}"
            )
        owned_consumers = tuple(sorted(consumers[parameter]))
        rows.append(
            ReproductionExecutionRequirement(
                definition.package,
                parameter,
                kind,
                owned_consumers,
                canonical_digest(
                    {
                        "package": definition.package,
                        "parameter": parameter,
                        "kind": kind.value,
                        "consumers": owned_consumers,
                    }
                ),
            )
        )
    return tuple(rows)


def _requirements_for_study(
    definition: ReproductionDefinition,
    study_factory: str,
) -> tuple[ReproductionExecutionRequirement, ...]:
    studies = resolve_study_factory_bindings(definition)
    if study_factory not in {row.qualname for row in studies}:
        raise ReproductionResearchOSCompileError(
            f"{definition.package} has no Study factory {study_factory!r}"
        )
    study_consumer = f"study:{study_factory}"
    return tuple(
        requirement
        for requirement in resolve_execution_requirements(definition)
        if study_consumer in requirement.consumers
        or any(
            consumer.startswith("method:")
            for consumer in requirement.consumers
        )
    )


def _validate_requirement_value(
    requirement: ReproductionExecutionRequirement,
    value: JsonValue,
) -> None:
    if requirement.kind is ReproductionExecutionRequirementKind.CAPABILITY_ID:
        if type(value) is not str or not value.strip():
            raise ValueError(
                f"{requirement.package} execution parameter "
                f"{requirement.parameter} must be non-empty text"
            )
        return
    if requirement.kind is ReproductionExecutionRequirementKind.CAPABILITY_CLOSURE:
        if type(value) is not tuple or not value:
            raise ValueError(
                f"{requirement.package} capability closure "
                f"{requirement.parameter} must be a non-empty sequence"
            )
        if (
            any(type(row) is not str or not row.strip() for row in value)
            or len(value) != len(set(value))
        ):
            raise ValueError(
                f"{requirement.package} capability closure "
                f"{requirement.parameter} must contain unique canonical text"
            )
        return
    if requirement.kind is ReproductionExecutionRequirementKind.PAPER_OPTION:
        if isinstance(value, Mapping) or type(value) is tuple or value is None:
            raise ValueError(
                f"{requirement.package} paper option {requirement.parameter} "
                "must be a finite JSON scalar"
            )
        return
    raise TypeError("unsupported reproduction execution requirement kind")


def bind_reproduction_execution(
    definition: ReproductionDefinition,
    *,
    binding_id: str,
    study_factory: str,
    benchmark_id: str,
    benchmark_split_id: str | None = None,
    values: Mapping[str, object],
    resolution_proof_digests: tuple[str, ...] = (),
) -> ReproductionExecutionBinding:
    """Bind exactly one Study lane; missing/extra values fail closed."""

    if type(definition) is not ReproductionDefinition:
        raise TypeError("reproduction execution binding requires definition")
    if benchmark_id not in definition.catalog.benchmark_ids:
        raise ReproductionResearchOSCompileError(
            f"{definition.package} benchmark {benchmark_id!r} is outside paper catalog"
        )
    studies = resolve_study_factory_bindings(definition)
    study = next(
        (row for row in studies if row.qualname == study_factory),
        None,
    )
    if study is None:
        raise ReproductionResearchOSCompileError(
            f"{definition.package} has no Study factory {study_factory!r}"
        )
    method_split_parameters: tuple[str, ...] = ()
    method_assets = tuple(
        row
        for row in definition.assets
        if row.kind is ReproductionAssetKind.METHOD_PROGRAM
    )
    method = None
    if method_assets:
        method = resolve_method_program_binding(definition)
        if method.factory is not None:
            method_split_parameters = tuple(
                name
                for name in method.factory.unresolved_parameters
                if name in _BENCHMARK_SPLIT_PARAMETERS
            )
    has_split_axis = (
        study.benchmark_split_parameter is not None
        or bool(method_split_parameters)
    )
    if has_split_axis:
        if (
            type(benchmark_split_id) is not str
            or not benchmark_split_id.strip()
            or benchmark_split_id != benchmark_split_id.strip()
        ):
            raise ReproductionResearchOSCompileError(
                f"{definition.package} execution lane requires exact benchmark_split_id"
            )
    elif benchmark_split_id is not None:
        raise ReproductionResearchOSCompileError(
            f"{definition.package} Study lane has no external benchmark split axis"
        )

    if not isinstance(values, Mapping):
        raise TypeError("reproduction execution values must be a mapping")
    frozen = freeze_json({key: values[key] for key in sorted(values)})
    if not isinstance(frozen, Mapping):
        raise TypeError("reproduction execution values must freeze to object")

    requirements = _requirements_for_study(definition, study_factory)
    expected = tuple(row.parameter for row in requirements)
    actual = tuple(sorted(frozen))
    if actual != expected:
        raise ReproductionResearchOSCompileError(
            f"{definition.package} execution binding value set drifted: "
            f"expected={expected}, actual={actual}"
        )
    for requirement in requirements:
        _validate_requirement_value(
            requirement,
            frozen[requirement.parameter],
        )

    if method is not None:
        if method.factory is not None:
            module = importlib.import_module(method.module)
            factory = getattr(module, method.qualname)
            signature = inspect.signature(factory)
            bound = signature.bind_partial(
                *method.factory.args,
                **dict(method.factory.kwargs),
            )
            bound_values = dict(frozen)
            if benchmark_split_id is not None:
                for parameter in method_split_parameters:
                    bound_values[parameter] = benchmark_split_id
            for parameter, value in bound_values.items():
                if parameter not in signature.parameters:
                    continue
                if parameter in bound.arguments:
                    if canonical_digest(bound.arguments[parameter]) != canonical_digest(value):
                        raise ReproductionResearchOSCompileError(
                            f"{definition.package} Study/Method binding disagrees for "
                            f"{parameter}"
                        )

    return ReproductionExecutionBinding(
        definition.package,
        binding_id,
        study_factory,
        benchmark_id,
        benchmark_split_id,
        frozen,
        tuple(row.requirement_digest for row in requirements),
        resolution_proof_digests,
    )


def expand_reproduction_benchmark_lanes(
    definition: ReproductionDefinition,
    *,
    study_factory: str,
    benchmark: BenchmarkTaskSet,
    values: Mapping[str, object],
    resolution_proof_digests: tuple[str, ...] = (),
) -> tuple[ReproductionExecutionBinding, ...]:
    """Expand one immutable benchmark cut into exact Research OS execution lanes.

    Benchmark split identity is platform-owned.  A split-aware Study gets one
    lane per split declared by the bound BenchmarkTaskSet; no default split is
    invented.  A Study without an external split axis gets exactly one cut lane.
    """

    if type(definition) is not ReproductionDefinition:
        raise TypeError("benchmark lane expansion requires reproduction definition")
    if not isinstance(benchmark, BenchmarkTaskSet):
        raise TypeError("benchmark lane expansion requires BenchmarkTaskSet")
    if benchmark.benchmark_id not in definition.catalog.benchmark_ids:
        raise ReproductionResearchOSCompileError(
            f"{definition.package} benchmark {benchmark.benchmark_id!r} is outside "
            "paper catalog"
        )
    studies = resolve_study_factory_bindings(definition)
    study = next(
        (row for row in studies if row.qualname == study_factory),
        None,
    )
    if study is None:
        raise ReproductionResearchOSCompileError(
            f"{definition.package} has no Study factory {study_factory!r}"
        )

    method_split_axis = False
    method_assets = tuple(
        row
        for row in definition.assets
        if row.kind is ReproductionAssetKind.METHOD_PROGRAM
    )
    if method_assets:
        method = resolve_method_program_binding(definition)
        if method.factory is not None:
            method_split_axis = any(
                name in _BENCHMARK_SPLIT_PARAMETERS
                for name in method.factory.unresolved_parameters
            )
    split_aware = (
        study.benchmark_split_parameter is not None
        or method_split_axis
    )

    if split_aware:
        if not benchmark.splits:
            raise ReproductionResearchOSCompileError(
                f"{definition.package} split-aware Study cannot bind benchmark "
                f"{benchmark.benchmark_id!r} without declared TaskSetSplit entries"
            )
        split_ids = tuple(row.split_id for row in benchmark.splits)
    else:
        split_ids = (None,)

    bindings: list[ReproductionExecutionBinding] = []
    for split_id in split_ids:
        frozen_values = freeze_json({
            key: values[key]
            for key in sorted(values)
        })
        lane_identity = canonical_digest(
            {
                "package": definition.package,
                "study_factory": study_factory,
                "benchmark_cut_digest": benchmark.cut_digest,
                "benchmark_split_id": split_id,
                "execution_values": frozen_values,
                "resolution_proof_digests": tuple(
                    sorted(resolution_proof_digests)
                ),
            }
        )
        binding_id = (
            f"{benchmark.benchmark_id}.{benchmark.revision_id}."
            f"{lane_identity[:12]}"
        )
        bindings.append(
            bind_reproduction_execution(
                definition,
                binding_id=binding_id,
                study_factory=study_factory,
                benchmark_id=benchmark.benchmark_id,
                benchmark_split_id=split_id,
                values=values,
                resolution_proof_digests=resolution_proof_digests,
            )
        )
    return tuple(bindings)


def resolve_reproduction_execution_variants(
    definition: ReproductionDefinition,
    *,
    study_factory: str,
    capability_resolver: ReproductionCapabilityRequirementResolverPort | None = None,
) -> tuple[ReproductionExecutionResolution, ...]:
    """Resolve all non-benchmark closure axes without inventing scientific values.

    Enum paper options expand exhaustively from the paper-owned Study type.
    Capability values must come from an authoritative CapabilitySelectionView.
    """

    if type(definition) is not ReproductionDefinition:
        raise TypeError("reproduction execution variants require definition")
    study = next(
        (
            row
            for row in resolve_study_factory_bindings(definition)
            if row.qualname == study_factory
        ),
        None,
    )
    if study is None:
        raise ReproductionResearchOSCompileError(
            f"{definition.package} has no Study factory {study_factory!r}"
        )
    module = importlib.import_module(study.module)
    factory = getattr(module, study.qualname)
    hints = get_type_hints(factory)
    requirements = _requirements_for_study(definition, study_factory)
    if not requirements:
        return (
            ReproductionExecutionResolution(
                definition.package,
                study_factory,
                {},
                (),
            ),
        )

    axes: list[tuple[tuple[JsonValue, str], ...]] = []
    for requirement in requirements:
        if requirement.kind is ReproductionExecutionRequirementKind.PAPER_OPTION:
            annotation = hints.get(
                requirement.parameter,
                inspect.Signature.empty,
            )
            if not (
                inspect.isclass(annotation)
                and issubclass(annotation, Enum)
            ):
                raise ReproductionResearchOSCompileError(
                    f"{definition.package} paper option {requirement.parameter!r} "
                    "must be a typed Enum or have a package-owned default"
                )
            members = tuple(annotation)
            if not members:
                raise ReproductionResearchOSCompileError(
                    f"{definition.package} paper option Enum is empty: "
                    f"{requirement.parameter}"
                )
            axes.append(
                tuple(
                    (
                        freeze_json(member.value),
                        canonical_digest({
                            "requirement_digest": requirement.requirement_digest,
                            "option_type": (
                                f"{annotation.__module__}.{annotation.__qualname__}"
                            ),
                            "option_name": member.name,
                            "option_value": freeze_json(member.value),
                        }),
                    )
                    for member in members
                )
            )
            continue

        if capability_resolver is None or not isinstance(
            capability_resolver,
            ReproductionCapabilityRequirementResolverPort,
        ):
            raise ReproductionResearchOSCompileError(
                f"{definition.package} capability requirement "
                f"{requirement.parameter!r} requires platform capability resolution"
            )
        view = capability_resolver.resolve(requirement)
        if type(view) is not CapabilitySelectionView:
            raise TypeError(
                "reproduction capability resolver must return CapabilitySelectionView"
            )
        capability_ids = tuple(
            sorted(descriptor.capability_id for descriptor in view.descriptors)
        )
        if len(capability_ids) != len(set(capability_ids)):
            raise ValueError("resolved reproduction capability ids must be unique")
        if requirement.kind is ReproductionExecutionRequirementKind.CAPABILITY_ID:
            if len(capability_ids) != 1:
                raise ReproductionResearchOSCompileError(
                    f"{definition.package} capability id requirement "
                    f"{requirement.parameter!r} resolved {len(capability_ids)} providers"
                )
            value: JsonValue = capability_ids[0]
        elif requirement.kind is (
            ReproductionExecutionRequirementKind.CAPABILITY_CLOSURE
        ):
            if not capability_ids:
                raise ReproductionResearchOSCompileError(
                    f"{definition.package} capability closure "
                    f"{requirement.parameter!r} resolved empty"
                )
            value = capability_ids
        else:
            raise TypeError("unsupported reproduction execution requirement kind")
        axes.append(
            ((
                value,
                canonical_digest({
                    "requirement_digest": requirement.requirement_digest,
                    "capability_selection_view_digest": view.view_digest,
                    "source_cut_digest": view.source_cut_digest,
                    "selection_provenance_digest": (
                        view.selection_provenance_digest
                    ),
                    "capability_ids": capability_ids,
                }),
            ),)
        )

    resolutions: list[ReproductionExecutionResolution] = []
    for combination in product(*axes):
        values = {
            requirement.parameter: combination[index][0]
            for index, requirement in enumerate(requirements)
        }
        proofs = tuple(
            combination[index][1]
            for index in range(len(requirements))
        )
        resolutions.append(
            ReproductionExecutionResolution(
                definition.package,
                study_factory,
                values,
                proofs,
            )
        )
    return tuple(
        sorted(
            resolutions,
            key=lambda row: row.resolution_digest,
        )
    )


def expand_resolved_reproduction_benchmark_lanes(
    definition: ReproductionDefinition,
    *,
    study_factory: str,
    benchmark: BenchmarkTaskSet,
    capability_resolver: ReproductionCapabilityRequirementResolverPort | None = None,
) -> tuple[ReproductionExecutionBinding, ...]:
    """One-call closure + benchmark expansion for an executable paper Study."""

    bindings: list[ReproductionExecutionBinding] = []
    for resolution in resolve_reproduction_execution_variants(
        definition,
        study_factory=study_factory,
        capability_resolver=capability_resolver,
    ):
        bindings.extend(
            expand_reproduction_benchmark_lanes(
                definition,
                study_factory=study_factory,
                benchmark=benchmark,
                values=resolution.values,
                resolution_proof_digests=resolution.proof_digests,
            )
        )
    ordered = tuple(
        sorted(
            bindings,
            key=lambda row: row.binding_digest,
        )
    )
    identities = tuple((row.package, row.binding_id) for row in ordered)
    if len(identities) != len(set(identities)):
        raise ReproductionResearchOSCompileError(
            "resolved reproduction lane identities must be unique"
        )
    return ordered


def _coerce_study_value(annotation: object, value: JsonValue) -> object:
    if (
        inspect.isclass(annotation)
        and issubclass(annotation, Enum)
        and type(value) in {str, int}
    ):
        return annotation(value)
    return value


def materialize_reproduction_study(
    definition: ReproductionDefinition,
    binding: ReproductionExecutionBinding,
    benchmark: BenchmarkTaskSet,
) -> ResearchStudyDefinition:
    """Materialize the exact Study selected by one execution binding."""

    if type(definition) is not ReproductionDefinition:
        raise TypeError("reproduction Study materialization requires definition")
    if type(binding) is not ReproductionExecutionBinding:
        raise TypeError("reproduction Study materialization requires binding")
    if binding.package != definition.package:
        raise ValueError("reproduction Study binding package drifted")
    if not isinstance(benchmark, BenchmarkTaskSet):
        raise TypeError("reproduction Study materialization requires BenchmarkTaskSet")
    if benchmark.benchmark_id != binding.benchmark_id:
        raise ValueError(
            "reproduction Study benchmark identity drifted from execution binding"
        )

    study = next(
        (
            row
            for row in resolve_study_factory_bindings(definition)
            if row.qualname == binding.study_factory
        ),
        None,
    )
    if study is None:
        raise ReproductionResearchOSCompileError(
            f"{definition.package} Study binding no longer resolves"
        )
    module = importlib.import_module(study.module)
    factory = getattr(module, study.qualname)
    hints = get_type_hints(factory)
    kwargs: dict[str, object] = {
        study.benchmark_parameter: benchmark,
    }
    split_parameter = study.benchmark_split_parameter
    if split_parameter is not None:
        if binding.benchmark_split_id is None:
            raise ReproductionResearchOSCompileError(
                f"{definition.package} Study lane lost benchmark split identity"
            )
        try:
            benchmark.selected_tasks(binding.benchmark_split_id)
        except KeyError as exc:
            raise ReproductionResearchOSCompileError(
                f"{definition.package} benchmark split is not present in the bound "
                f"BenchmarkTaskSet: {binding.benchmark_split_id!r}"
            ) from exc
        kwargs[split_parameter] = binding.benchmark_split_id
    for requirement in _requirements_for_study(definition, study.qualname):
        if f"study:{study.qualname}" not in requirement.consumers:
            continue
        kwargs[requirement.parameter] = _coerce_study_value(
            hints.get(requirement.parameter, inspect.Signature.empty),
            binding.values[requirement.parameter],
        )
    try:
        materialized = factory(**kwargs)
    except Exception as exc:
        raise ReproductionResearchOSCompileError(
            f"{definition.package} bound Study factory failed to materialize: "
            f"{study.qualname}"
        ) from exc
    if type(materialized) is not ResearchStudyDefinition:
        raise ReproductionResearchOSCompileError(
            f"{definition.package} bound Study factory returned wrong type"
        )
    return materialized


def materialize_reproduction_method_program(
    definition: ReproductionDefinition,
    binding: ReproductionExecutionBinding,
) -> api.ResearchMethodProgramImplementation | None:
    """Resolve the exact MethodProgram identity for one bound execution lane."""

    method_assets = tuple(
        row
        for row in definition.assets
        if row.kind is ReproductionAssetKind.METHOD_PROGRAM
    )
    if not method_assets:
        return None
    method = resolve_method_program_binding(definition)
    if method.binding_kind == "symbol":
        return api.ResearchMethodProgramImplementation.from_symbol(
            "method",
            module=method.module,
            qualname=method.qualname,
        )
    assert method.factory is not None
    merged_kwargs = dict(method.factory.kwargs)
    if binding.benchmark_split_id is not None:
        for parameter in method.factory.unresolved_parameters:
            if parameter in _BENCHMARK_SPLIT_PARAMETERS:
                merged_kwargs[parameter] = binding.benchmark_split_id
    for requirement in _requirements_for_study(
        definition,
        binding.study_factory,
    ):
        if any(
            consumer == f"method:{method.qualname}"
            for consumer in requirement.consumers
        ):
            merged_kwargs[requirement.parameter] = binding.values[
                requirement.parameter
            ]
    return api.ResearchMethodProgramImplementation.from_factory(
        "method",
        module=method.module,
        qualname=method.qualname,
        args=method.factory.args,
        kwargs=merged_kwargs,
    )


def resolve_method_program_binding(
    definition: ReproductionDefinition,
) -> ReproductionMethodProgramBinding:
    """Resolve one declared MethodProgram symbol/factory without fallback."""

    if type(definition) is not ReproductionDefinition:
        raise TypeError("reproduction Research OS compilation requires definition")
    asset = _asset(definition, ReproductionAssetKind.METHOD_PROGRAM)
    module_name = _module_from_asset(definition, asset)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ReproductionResearchOSCompileError(
            f"{definition.package} MethodProgram module cannot be imported: "
            f"{module_name}"
        ) from exc

    exported = getattr(module, "__all__", ())
    if type(exported) not in {list, tuple}:
        raise ReproductionResearchOSCompileError(
            f"{definition.package} MethodProgram module __all__ must be explicit"
        )
    if any(type(name) is not str or not name for name in exported):
        raise ReproductionResearchOSCompileError(
            f"{definition.package} MethodProgram module has invalid __all__"
        )

    factory = definition.method_program_factory
    if factory is not None:
        if factory.qualname not in exported:
            raise ReproductionResearchOSCompileError(
                f"{definition.package} declared MethodProgram factory is not exported: "
                f"{factory.qualname}"
            )
        value = getattr(module, factory.qualname, None)
        if not callable(value):
            raise ReproductionResearchOSCompileError(
                f"{definition.package} declared MethodProgram factory is not callable: "
                f"{factory.qualname}"
            )
        try:
            parameters = inspect.signature(value).parameters
        except (TypeError, ValueError) as exc:
            raise ReproductionResearchOSCompileError(
                f"{definition.package} MethodProgram factory signature is unavailable"
            ) from exc
        unknown = tuple(
            name for name in factory.unresolved_parameters if name not in parameters
        )
        if unknown:
            raise ReproductionResearchOSCompileError(
                f"{definition.package} factory declares unknown unresolved parameters: "
                f"{unknown}"
            )
        if not factory.exact:
            return ReproductionMethodProgramBinding(
                definition.package,
                asset,
                module_name,
                factory.qualname,
                None,
                "factory",
                factory,
            )
        try:
            implementation = api.ResearchMethodProgramImplementation.from_factory(
                "method",
                module=module_name,
                qualname=factory.qualname,
                args=factory.args,
                kwargs=factory.kwargs,
            )
        except (TypeError, ValueError) as exc:
            raise ReproductionResearchOSCompileError(
                f"{definition.package} exact MethodProgram factory failed to materialize"
            ) from exc
        return ReproductionMethodProgramBinding(
            definition.package,
            asset,
            module_name,
            factory.qualname,
            implementation.program_digest,
            "factory",
            factory,
        )

    candidates: list[tuple[str, MethodProgram]] = []
    for name in exported:
        value = getattr(module, name, None)
        if type(value) is MethodProgram:
            candidates.append((name, value))
    if len(candidates) != 1:
        raise ReproductionResearchOSCompileError(
            f"{definition.package} must export exactly one MethodProgram symbol or "
            "declare method_program_factory; "
            f"symbols={tuple(name for name, _ in candidates)}"
        )
    qualname, program = candidates[0]
    return ReproductionMethodProgramBinding(
        definition.package,
        asset,
        module_name,
        qualname,
        program.program_digest,
    )


def resolve_research_program_bindings(
    definition: ReproductionDefinition,
) -> tuple[ReproductionMachineProgramBinding, ...]:
    """Resolve every declared ResearchProgram asset into exact Machine IR identity."""

    if type(definition) is not ReproductionDefinition:
        raise TypeError("reproduction Research OS compilation requires definition")
    assets = tuple(
        row
        for row in definition.assets
        if row.kind is ReproductionAssetKind.RESEARCH_PROGRAM
    )
    bindings: list[ReproductionMachineProgramBinding] = []
    for asset in assets:
        module_name = _module_from_asset(definition, asset)
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            raise ReproductionResearchOSCompileError(
                f"{definition.package} ResearchProgram module cannot be imported: "
                f"{module_name}"
            ) from exc
        exported = getattr(module, "__all__", ())
        if type(exported) not in {list, tuple}:
            raise ReproductionResearchOSCompileError(
                f"{definition.package} ResearchProgram module __all__ must be explicit"
            )
        candidates: dict[str, tuple[str, MachineResearchProgram]] = {}
        for name in exported:
            if type(name) is not str or not name:
                raise ReproductionResearchOSCompileError(
                    f"{definition.package} ResearchProgram module has invalid __all__"
                )
            value = getattr(module, name, None)
            if type(value) is MachineResearchProgram:
                candidates.setdefault(value.program_digest, (name, value))
        if not candidates:
            raise ReproductionResearchOSCompileError(
                f"{definition.package} must export at least one ResearchProgram from "
                f"{asset.path}"
            )
        for program_digest, (qualname, program) in sorted(candidates.items()):
            bindings.append(
                ReproductionMachineProgramBinding(
                    definition.package,
                    asset,
                    module_name,
                    qualname,
                    program.program_id,
                    program.kind.value,
                    program_digest,
                )
            )
    ordered = tuple(
        sorted(
            bindings,
            key=lambda row: (
                row.asset.path,
                row.program_id,
                row.program_digest,
                row.qualname,
            ),
        )
    )
    identities = tuple(
        (row.module, row.program_id, row.program_digest)
        for row in ordered
    )
    if len(identities) != len(set(identities)):
        raise ReproductionResearchOSCompileError(
            f"{definition.package} declares duplicate ResearchProgram identities"
        )
    return ordered


def _machine_dependency_document(
    binding: ReproductionMachineProgramBinding,
) -> dict[str, str]:
    return {
        "asset_path": binding.asset.path,
        "module": binding.module,
        "qualname": binding.qualname,
        "program_id": binding.program_id,
        "machine_kind": binding.machine_kind,
        "program_digest": binding.program_digest,
    }


def _validated_execution_binding(
    definition: ReproductionDefinition,
    binding: ReproductionExecutionBinding | None,
) -> ReproductionExecutionBinding | None:
    if binding is None:
        return None
    if type(binding) is not ReproductionExecutionBinding:
        raise TypeError("bound reproduction compilation requires execution binding")
    if binding.package != definition.package:
        raise ValueError("reproduction execution binding package drifted")
    validated = bind_reproduction_execution(
        definition,
        binding_id=binding.binding_id,
        study_factory=binding.study_factory,
        benchmark_id=binding.benchmark_id,
        benchmark_split_id=binding.benchmark_split_id,
        values=binding.values,
    )
    if validated.binding_digest != binding.binding_digest:
        raise ValueError("reproduction execution binding identity drifted")
    return validated


def _method_factory_call(
    definition: ReproductionDefinition,
    method: ReproductionMethodProgramBinding,
    binding: ReproductionExecutionBinding | None,
) -> tuple[tuple[JsonValue, ...], Mapping[str, JsonValue]]:
    if method.factory is None:
        raise TypeError("reproduction MethodProgram symbol has no factory call")
    kwargs: dict[str, JsonValue] = dict(method.factory.kwargs)
    if binding is not None:
        if binding.benchmark_split_id is not None:
            for parameter in method.factory.unresolved_parameters:
                if parameter in _BENCHMARK_SPLIT_PARAMETERS:
                    kwargs[parameter] = binding.benchmark_split_id
        for requirement in _requirements_for_study(
            definition,
            binding.study_factory,
        ):
            if f"method:{method.qualname}" in requirement.consumers:
                kwargs[requirement.parameter] = binding.values[
                    requirement.parameter
                ]
    return method.factory.args, kwargs


def _compile_reproduction_research_program(
    definition: ReproductionDefinition,
    execution_binding: ReproductionExecutionBinding | None,
) -> api.ResearchProgram:
    if type(definition) is not ReproductionDefinition:
        raise TypeError("reproduction Research OS compilation requires definition")
    execution_binding = _validated_execution_binding(
        definition,
        execution_binding,
    )
    study = _asset(definition, ReproductionAssetKind.STUDY)
    all_study_factories = resolve_study_factory_bindings(definition)
    if execution_binding is None:
        study_factories = all_study_factories
        execution_requirements = resolve_execution_requirements(definition)
        benchmark_ids = definition.catalog.benchmark_ids
        program_id = definition.package
    else:
        study_factories = tuple(
            row
            for row in all_study_factories
            if row.qualname == execution_binding.study_factory
        )
        if len(study_factories) != 1:
            raise ReproductionResearchOSCompileError(
                f"{definition.package} bound Study factory identity drifted"
            )
        execution_requirements = _requirements_for_study(
            definition,
            execution_binding.study_factory,
        )
        benchmark_ids = (execution_binding.benchmark_id,)
        program_id = (
            f"{definition.package}.{execution_binding.binding_id}"
        )

    machine_dependencies = resolve_research_program_bindings(definition)
    machine_dependency_documents = tuple(
        _machine_dependency_document(row)
        for row in machine_dependencies
    )
    method_assets = tuple(
        row
        for row in definition.assets
        if row.kind is ReproductionAssetKind.METHOD_PROGRAM
    )
    if len(method_assets) > 1:
        raise ReproductionResearchOSCompileError(
            f"{definition.package} declares multiple MethodProgram assets"
        )
    if not method_assets and not machine_dependencies:
        raise ReproductionResearchOSCompileError(
            f"{definition.package} has a Study but no executable MethodProgram/"
            "ResearchProgram asset"
        )

    builder = api.ResearchProgramBuilder(program_id)
    executable_definition_ids: list[str] = []
    if method_assets:
        method = resolve_method_program_binding(definition)
        effective_program_digest = method.program_digest
        effective_binding_digest = method.binding_digest
        factory_args: tuple[JsonValue, ...] | None = None
        factory_kwargs: Mapping[str, JsonValue] | None = None
        if method.factory is not None and (
            method.exact or execution_binding is not None
        ):
            factory_args, factory_kwargs = _method_factory_call(
                definition,
                method,
                execution_binding,
            )
            implementation = api.ResearchMethodProgramImplementation.from_factory(
                "method",
                module=method.module,
                qualname=method.qualname,
                args=factory_args,
                kwargs=factory_kwargs,
            )
            effective_program_digest = implementation.program_digest
            effective_binding_digest = canonical_digest(
                {
                    "factory_binding_digest": method.binding_digest,
                    "execution_binding_digest": (
                        None
                        if execution_binding is None
                        else execution_binding.binding_digest
                    ),
                    "program_digest": effective_program_digest,
                }
            )

        method_config = {
            "reproduction_package": definition.package,
            "reproduction_method_id": definition.identity.method_id,
            "reproduction_definition_digest": definition.definition_digest,
            "asset_path": method.asset.path,
            "binding_kind": method.binding_kind,
            "binding_digest": effective_binding_digest,
            "program_digest": effective_program_digest,
            "execution_binding_digest": (
                None
                if execution_binding is None
                else execution_binding.binding_digest
            ),
            "research_program_dependencies": machine_dependency_documents,
        }
        if method.binding_kind == "symbol":
            builder.method_program(
                "method",
                module=method.module,
                qualname=method.qualname,
                config=method_config,
            )
        elif effective_program_digest is not None:
            assert factory_args is not None and factory_kwargs is not None
            builder.method_program_factory(
                "method",
                module=method.module,
                qualname=method.qualname,
                args=factory_args,
                kwargs=factory_kwargs,
                config=method_config,
            )
        else:
            builder.definition(
                "method",
                kind=api.ResearchDefinitionKind.METHOD,
                config={
                    **method_config,
                    "authority": "execution-binding-required",
                    "execution_requirement_digests": tuple(
                        row.requirement_digest
                        for row in execution_requirements
                        if any(
                            consumer.startswith("method:")
                            for consumer in row.consumers
                        )
                    ),
                },
            )
        executable_definition_ids.append("method")
        primary_executable_digest = effective_binding_digest
    else:
        for index, machine_binding in enumerate(machine_dependencies):
            definition_id = f"machine.{index:02d}"
            builder.definition(
                definition_id,
                kind=api.ResearchDefinitionKind.CUSTOM,
                config={
                    "authority": "research-machine-program",
                    **_machine_dependency_document(machine_binding),
                },
            )
            executable_definition_ids.append(definition_id)
        primary_executable_digest = machine_dependencies[0].program_digest

    builder.protocol(
        "study",
        config={
            "reproduction_package": definition.package,
            "reproduction_method_id": definition.identity.method_id,
            "reproduction_definition_digest": definition.definition_digest,
            "asset_path": study.path,
            "study_factories": tuple(
                {
                    "module": study_binding.module,
                    "qualname": study_binding.qualname,
                    "benchmark_parameter": study_binding.benchmark_parameter,
                    "required_parameters": study_binding.required_parameters,
                    "binding_digest": study_binding.binding_digest,
                }
                for study_binding in study_factories
            ),
            "execution_requirements": tuple(
                {
                    "parameter": requirement.parameter,
                    "kind": requirement.kind.value,
                    "consumers": requirement.consumers,
                    "requirement_digest": requirement.requirement_digest,
                }
                for requirement in execution_requirements
            ),
            "execution_binding": (
                None
                if execution_binding is None
                else {
                    "binding_id": execution_binding.binding_id,
                    "binding_digest": execution_binding.binding_digest,
                    "study_factory": execution_binding.study_factory,
                    "benchmark_id": execution_binding.benchmark_id,
                    "benchmark_split_id": execution_binding.benchmark_split_id,
                    "values": execution_binding.values,
                }
            ),
        },
    )

    benchmark_definition_ids: list[str] = []
    for benchmark_id in benchmark_ids:
        definition_id = f"benchmark.{benchmark_id}"
        builder.benchmark(
            definition_id,
            config={
                "benchmark_id": benchmark_id,
                "reproduction_package": definition.package,
                "execution_binding_digest": (
                    None
                    if execution_binding is None
                    else execution_binding.binding_digest
                ),
            },
        )
        benchmark_definition_ids.append(definition_id)

    builder.experiment(
        "reproduction",
        definitions=(
            *tuple(executable_definition_ids),
            "study",
            *tuple(benchmark_definition_ids),
        ),
        outputs=(
            api.ResearchOutputSpec(
                "report",
                api.ResearchValueKind.ARTIFACT,
            ),
        ),
        config={
            "reproduction_package": definition.package,
            "reproduction_method_id": definition.identity.method_id,
            "reproduction_lifecycle": definition.lifecycle.value,
            "reproduction_definition_digest": definition.definition_digest,
            "primary_executable_digest": primary_executable_digest,
            "study_asset": study.path,
            "benchmark_ids": benchmark_ids,
            "research_program_dependencies": machine_dependency_documents,
            "execution_requirement_digests": tuple(
                requirement.requirement_digest
                for requirement in execution_requirements
            ),
            "execution_binding_digest": (
                None
                if execution_binding is None
                else execution_binding.binding_digest
            ),
        },
    )
    return builder.freeze()


def compile_reproduction_research_program(
    definition: ReproductionDefinition,
) -> api.ResearchProgram:
    """Compile one reproduction template onto the current Product Research OS."""

    return _compile_reproduction_research_program(definition, None)


def compile_bound_reproduction_research_program(
    definition: ReproductionDefinition,
    execution_binding: ReproductionExecutionBinding,
) -> api.ResearchProgram:
    """Compile one exact benchmark/treatment lane onto Product Research OS."""

    return _compile_reproduction_research_program(
        definition,
        execution_binding,
    )


_NON_EXECUTABLE_LIFECYCLES = frozenset(
    {
        ReproductionLifecycle.CATALOGUED,
        ReproductionLifecycle.PAPER_ONLY,
        ReproductionLifecycle.ARTIFACT_ONLY,
    }
)


def is_research_os_executable(definition: ReproductionDefinition) -> bool:
    """Return whether a declaration owns the exact assets required by Research OS.

    This is capability-derived, never filename-derived and never a lifecycle
    downgrade. A Study plus at least one canonical executable IR is mandatory.
    """

    if type(definition) is not ReproductionDefinition:
        raise TypeError("reproduction executable check requires definition")
    kinds = tuple(asset.kind for asset in definition.assets)
    has_study = ReproductionAssetKind.STUDY in kinds
    has_executable = any(
        kind in {
            ReproductionAssetKind.METHOD_PROGRAM,
            ReproductionAssetKind.RESEARCH_PROGRAM,
        }
        for kind in kinds
    )
    return has_study and has_executable


def discover_reproduction_definitions() -> tuple[ReproductionDefinition, ...]:
    """Load every package-local typed reproduction declaration in canonical order."""

    root = Path(__file__).resolve().parent
    definitions: list[ReproductionDefinition] = []
    for package_dir in sorted(root.iterdir(), key=lambda path: path.name):
        definition_path = package_dir / "definition.py"
        if not package_dir.is_dir() or not definition_path.is_file():
            continue
        module_name = f"research.reproductions.{package_dir.name}.definition"
        module = importlib.import_module(module_name)
        definition = getattr(module, "REPRODUCTION", None)
        if type(definition) is not ReproductionDefinition:
            raise ReproductionResearchOSCompileError(
                f"{module_name} must export typed REPRODUCTION"
            )
        if definition.package != package_dir.name:
            raise ReproductionResearchOSCompileError(
                f"reproduction package identity drifted: directory={package_dir.name} "
                f"definition={definition.package}"
            )
        definitions.append(definition)
    packages = tuple(row.package for row in definitions)
    if len(packages) != len(set(packages)):
        raise ReproductionResearchOSCompileError(
            "repository reproduction package identities must be unique"
        )
    return tuple(definitions)


def executable_reproduction_definitions() -> tuple[ReproductionDefinition, ...]:
    """Return every existing reproduction that can enter the current Research OS."""

    definitions = discover_reproduction_definitions()
    invalid = tuple(
        row.package
        for row in definitions
        if row.lifecycle not in _NON_EXECUTABLE_LIFECYCLES
        and not is_research_os_executable(row)
    )
    if invalid:
        raise ReproductionResearchOSCompileError(
            "execution-bearing reproductions are missing Study/executable assets: "
            f"{invalid}"
        )
    return tuple(row for row in definitions if is_research_os_executable(row))


def compile_repository_reproduction_portfolio(
    portfolio_id: str = "repository-reproductions",
) -> api.ResearchPortfolio:
    """Compile every existing executable reproduction onto the latest Research OS."""

    return compile_reproduction_portfolio(
        portfolio_id,
        executable_reproduction_definitions(),
    )


def compile_resolved_reproduction_portfolio(
    portfolio_id: str,
    requests: tuple[ReproductionExecutionRequest, ...],
    *,
    capability_resolver: ReproductionCapabilityRequirementResolverPort | None = None,
) -> api.ResearchPortfolio:
    """Compile top-level lane requests without caller-authored execution bindings."""

    if type(requests) is not tuple or not requests:
        raise ValueError("resolved reproduction portfolio requires execution requests")
    if any(type(row) is not ReproductionExecutionRequest for row in requests):
        raise TypeError(
            "resolved reproduction portfolio requests must be typed"
        )
    request_digests = tuple(row.request_digest for row in requests)
    if len(request_digests) != len(set(request_digests)):
        raise ValueError("resolved reproduction execution requests must be unique")

    definitions = {
        row.package: row
        for row in discover_reproduction_definitions()
    }
    bindings: list[ReproductionExecutionBinding] = []
    for request in sorted(
        requests,
        key=lambda row: (
            row.package,
            row.study_factory,
            row.benchmark.benchmark_id,
            row.benchmark.revision_id,
            row.benchmark.cut_digest,
        ),
    ):
        definition = definitions.get(request.package)
        if definition is None:
            raise ReproductionResearchOSCompileError(
                f"unknown reproduction package in execution request: "
                f"{request.package}"
            )
        if not is_research_os_executable(definition):
            raise ReproductionResearchOSCompileError(
                f"{request.package} has no executable Study/Program authority"
            )
        bindings.extend(
            expand_resolved_reproduction_benchmark_lanes(
                definition,
                study_factory=request.study_factory,
                benchmark=request.benchmark,
                capability_resolver=capability_resolver,
            )
        )
    return compile_bound_reproduction_portfolio(
        portfolio_id,
        tuple(bindings),
    )


def compile_bound_reproduction_portfolio(
    portfolio_id: str,
    bindings: tuple[ReproductionExecutionBinding, ...],
) -> api.ResearchPortfolio:
    """Compile many exact execution lanes, including multiple lanes per paper."""

    if type(bindings) is not tuple or not bindings:
        raise ValueError("bound reproduction portfolio requires execution bindings")
    if any(type(row) is not ReproductionExecutionBinding for row in bindings):
        raise TypeError("bound reproduction portfolio bindings must be typed")
    identities = tuple((row.package, row.binding_id) for row in bindings)
    if len(identities) != len(set(identities)):
        raise ValueError(
            "bound reproduction portfolio binding identities must be unique"
        )
    definitions = {
        row.package: row for row in discover_reproduction_definitions()
    }
    unknown = tuple(
        sorted(
            package
            for package, _binding_id in identities
            if package not in definitions
        )
    )
    if unknown:
        raise ReproductionResearchOSCompileError(
            f"bound reproduction portfolio references unknown packages: {unknown}"
        )
    programs = tuple(
        compile_bound_reproduction_research_program(
            definitions[binding.package],
            binding,
        )
        for binding in sorted(
            bindings,
            key=lambda row: (row.package, row.binding_id),
        )
    )
    ids = tuple(program.program_id for program in programs)
    if len(ids) != len(set(ids)):
        raise ReproductionResearchOSCompileError(
            "bound reproduction portfolio produced duplicate program identities"
        )
    return api.ResearchPortfolio(portfolio_id, programs)

def compile_reproduction_portfolio(
    portfolio_id: str,
    definitions: tuple[ReproductionDefinition, ...],
) -> api.ResearchPortfolio:
    """Compile many independent paper reproductions into one schedulable portfolio."""

    if type(definitions) is not tuple or not definitions:
        raise ValueError("reproduction portfolio requires typed definitions")
    if any(type(row) is not ReproductionDefinition for row in definitions):
        raise TypeError("reproduction portfolio definitions must be typed")
    packages = tuple(row.package for row in definitions)
    if len(packages) != len(set(packages)):
        raise ValueError("reproduction portfolio packages must be unique")
    programs = tuple(
        compile_reproduction_research_program(row)
        for row in sorted(definitions, key=lambda row: row.package)
    )
    return api.ResearchPortfolio(portfolio_id, programs)


__all__ = [
    "ReproductionCapabilityRequirementResolverPort",
    "ReproductionExecutionBinding",
    "ReproductionExecutionRequirement",
    "ReproductionExecutionRequest",
    "ReproductionExecutionResolution",
    "ReproductionExecutionRequirementKind",
    "ReproductionMachineProgramBinding",
    "ReproductionMethodProgramBinding",
    "ReproductionStudyFactoryBinding",
    "ReproductionResearchOSCompileError",
    "bind_reproduction_execution",
    "compile_bound_reproduction_portfolio",
    "compile_bound_reproduction_research_program",
    "compile_reproduction_portfolio",
    "compile_resolved_reproduction_portfolio",
    "compile_reproduction_research_program",
    "compile_repository_reproduction_portfolio",
    "discover_reproduction_definitions",
    "executable_reproduction_definitions",
    "expand_reproduction_benchmark_lanes",
    "expand_resolved_reproduction_benchmark_lanes",
    "is_research_os_executable",
    "materialize_reproduction_method_program",
    "materialize_reproduction_study",
    "resolve_benchmark_split_consumers",
    "resolve_execution_requirements",
    "resolve_reproduction_execution_variants",
    "resolve_method_program_binding",
    "resolve_study_factory_bindings",
    "resolve_research_program_bindings",
]

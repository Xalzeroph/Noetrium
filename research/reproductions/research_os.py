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
from pathlib import Path, PurePosixPath
from typing import get_type_hints

from noetrium import api
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
    """Typed input required to close one reproduction execution."""

    BENCHMARK_SPLIT = "benchmark_split"
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


_EXECUTION_REQUIREMENT_KIND_BY_PARAMETER = {
    "split_id": ReproductionExecutionRequirementKind.BENCHMARK_SPLIT,
    "benchmark_split_id": ReproductionExecutionRequirementKind.BENCHMARK_SPLIT,
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
    values: Mapping[str, JsonValue]
    requirement_digests: tuple[str, ...]
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
        object.__setattr__(self, "values", frozen_values)
        object.__setattr__(self, "requirement_digests", digests)
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest(
                {
                    "package": self.package,
                    "binding_id": self.binding_id,
                    "study_factory": self.study_factory,
                    "benchmark_id": self.benchmark_id,
                    "values": frozen_values,
                    "requirement_digests": digests,
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
    def unresolved_parameters(self) -> tuple[str, ...]:
        return tuple(
            name for name in self.required_parameters
            if name != self.benchmark_parameter
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
    if requirement.kind in {
        ReproductionExecutionRequirementKind.BENCHMARK_SPLIT,
        ReproductionExecutionRequirementKind.CAPABILITY_ID,
    }:
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
    values: Mapping[str, object],
) -> ReproductionExecutionBinding:
    """Bind exactly one Study lane; missing/extra values fail closed."""

    if type(definition) is not ReproductionDefinition:
        raise TypeError("reproduction execution binding requires definition")
    if benchmark_id not in definition.catalog.benchmark_ids:
        raise ReproductionResearchOSCompileError(
            f"{definition.package} benchmark {benchmark_id!r} is outside paper catalog"
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

    method_assets = tuple(
        row
        for row in definition.assets
        if row.kind is ReproductionAssetKind.METHOD_PROGRAM
    )
    if method_assets:
        method = resolve_method_program_binding(definition)
        if method.factory is not None:
            module = importlib.import_module(method.module)
            factory = getattr(module, method.qualname)
            signature = inspect.signature(factory)
            bound = signature.bind_partial(
                *method.factory.args,
                **dict(method.factory.kwargs),
            )
            for parameter, value in frozen.items():
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
        frozen,
        tuple(row.requirement_digest for row in requirements),
    )


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


def compile_reproduction_research_program(
    definition: ReproductionDefinition,
) -> api.ResearchProgram:
    """Compile one executable+Study reproduction to the current Research OS IR.

    MethodProgram packages bind their exact UMM IR.  Reproductions whose primary
    executable is another Research Machine bind those exact program identities as
    platform-resolved executable requirements for the Experimentation closure.
    Nothing is downgraded to a plain callable.
    """

    if type(definition) is not ReproductionDefinition:
        raise TypeError("reproduction Research OS compilation requires definition")
    study = _asset(definition, ReproductionAssetKind.STUDY)
    study_factories = resolve_study_factory_bindings(definition)
    execution_requirements = resolve_execution_requirements(definition)
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

    # One top-level ResearchProgram represents one reproduction package, not the
    # underlying method identity. Different paper/version packages may share the
    # same method_id; package identity is the unique ResearchGraph namespace.
    builder = api.ResearchProgramBuilder(definition.package)
    executable_definition_ids: list[str] = []
    if method_assets:
        method = resolve_method_program_binding(definition)
        method_config = {
            "reproduction_package": definition.package,
            "reproduction_method_id": definition.identity.method_id,
            "reproduction_definition_digest": definition.definition_digest,
            "asset_path": method.asset.path,
            "binding_kind": method.binding_kind,
            "binding_digest": method.binding_digest,
            "program_digest": method.program_digest,
            "unresolved_parameters": (
                ()
                if method.factory is None
                else method.factory.unresolved_parameters
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
        elif method.exact:
            assert method.factory is not None
            builder.method_program_factory(
                "method",
                module=method.module,
                qualname=method.qualname,
                args=method.factory.args,
                kwargs=method.factory.kwargs,
                config=method_config,
            )
        else:
            builder.definition(
                "method",
                kind=api.ResearchDefinitionKind.METHOD,
                config={
                    **method_config,
                    "authority": "parameterized-method-program-factory",
                },
            )
        executable_definition_ids.append("method")
        primary_executable_digest = method.binding_digest
    else:
        for index, binding in enumerate(machine_dependencies):
            definition_id = f"machine.{index:02d}"
            builder.definition(
                definition_id,
                kind=api.ResearchDefinitionKind.CUSTOM,
                config={
                    "authority": "research-machine-program",
                    **_machine_dependency_document(binding),
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
                    "module": binding.module,
                    "qualname": binding.qualname,
                    "benchmark_parameter": binding.benchmark_parameter,
                    "required_parameters": binding.required_parameters,
                    "binding_digest": binding.binding_digest,
                }
                for binding in study_factories
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
        },
    )

    benchmark_definition_ids: list[str] = []
    for benchmark_id in definition.catalog.benchmark_ids:
        definition_id = f"benchmark.{benchmark_id}"
        builder.benchmark(
            definition_id,
            config={
                "benchmark_id": benchmark_id,
                "reproduction_package": definition.package,
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
            "benchmark_ids": definition.catalog.benchmark_ids,
            "research_program_dependencies": machine_dependency_documents,
            "execution_requirement_digests": tuple(
                requirement.requirement_digest
                for requirement in execution_requirements
            ),
        },
    )
    return builder.freeze()

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
    "ReproductionExecutionBinding",
    "ReproductionExecutionRequirement",
    "ReproductionExecutionRequirementKind",
    "ReproductionMachineProgramBinding",
    "ReproductionMethodProgramBinding",
    "ReproductionStudyFactoryBinding",
    "ReproductionResearchOSCompileError",
    "bind_reproduction_execution",
    "compile_reproduction_portfolio",
    "compile_reproduction_research_program",
    "compile_repository_reproduction_portfolio",
    "discover_reproduction_definitions",
    "executable_reproduction_definitions",
    "is_research_os_executable",
    "materialize_reproduction_method_program",
    "materialize_reproduction_study",
    "resolve_execution_requirements",
    "resolve_method_program_binding",
    "resolve_study_factory_bindings",
    "resolve_research_program_bindings",
]

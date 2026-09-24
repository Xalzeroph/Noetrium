"""Canonical compiler from reproduction declarations into the Research OS surface.

Reproduction packages own scientific semantics in their typed MethodProgram,
Study, benchmark and fidelity assets.  This module owns no paper-specific
semantics; it only proves those declared assets can be represented by the
current top-level ResearchProgram/ResearchPortfolio model.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import inspect
from pathlib import Path, PurePosixPath

from noetrium import api
from noetrium_platform.foundation.kernel.kernel import canonical_digest
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
                    "unresolved_parameters": binding.unresolved_parameters,
                    "binding_digest": binding.binding_digest,
                }
                for binding in study_factories
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
    "ReproductionMachineProgramBinding",
    "ReproductionMethodProgramBinding",
    "ReproductionStudyFactoryBinding",
    "ReproductionResearchOSCompileError",
    "compile_reproduction_portfolio",
    "compile_reproduction_research_program",
    "compile_repository_reproduction_portfolio",
    "discover_reproduction_definitions",
    "executable_reproduction_definitions",
    "is_research_os_executable",
    "resolve_method_program_binding",
    "resolve_study_factory_bindings",
    "resolve_research_program_bindings",
]

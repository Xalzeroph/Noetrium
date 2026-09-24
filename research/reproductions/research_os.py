"""Canonical compiler from reproduction declarations into the Research OS surface.

Reproduction packages own scientific semantics in their typed MethodProgram,
Study, benchmark and fidelity assets.  This module owns no paper-specific
semantics; it only proves those declared assets can be represented by the
current top-level ResearchProgram/ResearchPortfolio model.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from pathlib import PurePosixPath

from noetrium import api
from noetrium_platform.research.execution.machines.api import (
    ResearchProgram as MachineResearchProgram,
)
from noetrium_platform.research.execution.workflow.api import MethodProgram

from .contracts import (
    ReproductionAssetKind,
    ReproductionAssetRef,
    ReproductionDefinition,
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
class ReproductionMethodProgramBinding:
    package: str
    asset: ReproductionAssetRef
    module: str
    qualname: str
    program_digest: str

    def __post_init__(self) -> None:
        if not self.package:
            raise ValueError("reproduction MethodProgram binding package is required")
        if self.asset.kind is not ReproductionAssetKind.METHOD_PROGRAM:
            raise ValueError("reproduction MethodProgram binding asset kind drifted")
        if not self.module or not self.qualname:
            raise ValueError("reproduction MethodProgram import coordinates are required")
        if len(self.program_digest) != 64:
            raise ValueError("reproduction MethodProgram digest must be SHA-256 text")


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


def resolve_method_program_binding(
    definition: ReproductionDefinition,
) -> ReproductionMethodProgramBinding:
    """Resolve the one declared MethodProgram asset without guessing a fallback."""

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
    if type(exported) is not list and type(exported) is not tuple:
        raise ReproductionResearchOSCompileError(
            f"{definition.package} MethodProgram module __all__ must be explicit"
        )
    candidates: list[tuple[str, MethodProgram]] = []
    for name in exported:
        if type(name) is not str or not name:
            raise ReproductionResearchOSCompileError(
                f"{definition.package} MethodProgram module has invalid __all__"
            )
        value = getattr(module, name, None)
        if type(value) is MethodProgram:
            candidates.append((name, value))
    if len(candidates) != 1:
        raise ReproductionResearchOSCompileError(
            f"{definition.package} must export exactly one MethodProgram from "
            f"{asset.path}; found={tuple(name for name, _ in candidates)}"
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

    builder = api.ResearchProgramBuilder(definition.identity.method_id)
    executable_definition_ids: list[str] = []
    if method_assets:
        method = resolve_method_program_binding(definition)
        builder.method_program(
            "method",
            module=method.module,
            qualname=method.qualname,
            config={
                "reproduction_package": definition.package,
                "reproduction_definition_digest": definition.definition_digest,
                "asset_path": method.asset.path,
                "program_digest": method.program_digest,
                "research_program_dependencies": machine_dependency_documents,
            },
        )
        executable_definition_ids.append("method")
        primary_executable_digest = method.program_digest
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
            "reproduction_definition_digest": definition.definition_digest,
            "asset_path": study.path,
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
            "reproduction_lifecycle": definition.lifecycle.value,
            "reproduction_definition_digest": definition.definition_digest,
            "primary_executable_digest": primary_executable_digest,
            "study_asset": study.path,
            "benchmark_ids": definition.catalog.benchmark_ids,
            "research_program_dependencies": machine_dependency_documents,
        },
    )
    return builder.freeze()

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
    "ReproductionResearchOSCompileError",
    "compile_reproduction_portfolio",
    "compile_reproduction_research_program",
    "resolve_method_program_binding",
    "resolve_research_program_bindings",
]

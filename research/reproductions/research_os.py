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
from noetrium_platform.research.execution.workflow.api import MethodProgram

from .contracts import (
    ReproductionAssetKind,
    ReproductionAssetRef,
    ReproductionDefinition,
)


class ReproductionResearchOSCompileError(RuntimeError):
    pass


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


def compile_reproduction_research_program(
    definition: ReproductionDefinition,
) -> api.ResearchProgram:
    """Compile one MethodProgram+Study reproduction to the current Research OS IR."""

    if type(definition) is not ReproductionDefinition:
        raise TypeError("reproduction Research OS compilation requires definition")
    method = resolve_method_program_binding(definition)
    study = _asset(definition, ReproductionAssetKind.STUDY)

    builder = api.ResearchProgramBuilder(definition.identity.method_id)
    builder.method_program(
        "method",
        module=method.module,
        qualname=method.qualname,
        config={
            "reproduction_package": definition.package,
            "reproduction_definition_digest": definition.definition_digest,
            "asset_path": method.asset.path,
            "program_digest": method.program_digest,
        },
    )
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
            "method",
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
            "method_program_digest": method.program_digest,
            "study_asset": study.path,
            "benchmark_ids": definition.catalog.benchmark_ids,
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
    "ReproductionMethodProgramBinding",
    "ReproductionResearchOSCompileError",
    "compile_reproduction_portfolio",
    "compile_reproduction_research_program",
    "resolve_method_program_binding",
]

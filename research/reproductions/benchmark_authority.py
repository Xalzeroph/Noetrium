"""Repository benchmark authority for exact source-contained cuts.

This module discovers only benchmark authorities that are already fully closed
by repository source: a public exported zero-argument callable whose annotated
return type is the canonical BenchmarkSourceResolution. It never downloads
data, invents digests, chooses among multiple cuts, or guesses paper splits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import inspect
from pathlib import Path
from typing import get_type_hints

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.kernel.durability import sha256_file
from noetrium_platform.research.experimentation.lifecycle.api import (
    BenchmarkSourceResolution,
)

from .contracts import ReproductionDefinition
from .fleet import ReproductionBenchmarkSelection
from .research_os import (
    ReproductionResearchOSCompileError,
    ReproductionStudyFactoryBinding,
    resolve_benchmark_split_consumers,
    resolve_study_factory_bindings,
)


@dataclass(frozen=True, slots=True)
class RepositoryBenchmarkBinding:
    """One exact repository-owned benchmark resolution provider."""

    benchmark_package: str
    module: str
    qualname: str
    source_sha256: str
    resolution: BenchmarkSourceResolution
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name, value in (
            ("benchmark_package", self.benchmark_package),
            ("module", self.module),
            ("qualname", self.qualname),
        ):
            if type(value) is not str or not value.strip() or value != value.strip():
                raise ValueError(
                    f"repository benchmark binding {field_name} must be canonical text"
                )
        if (
            type(self.source_sha256) is not str
            or len(self.source_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in self.source_sha256)
        ):
            raise ValueError(
                "repository benchmark binding source_sha256 must be lowercase SHA-256"
            )
        if type(self.resolution) is not BenchmarkSourceResolution:
            raise TypeError(
                "repository benchmark binding requires BenchmarkSourceResolution"
            )
        if self.resolution.source.source_id != self.resolution.task_set.benchmark_id:
            raise ValueError(
                "repository benchmark source/task-set identity drifted"
            )
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest(
                {
                    "benchmark_package": self.benchmark_package,
                    "module": self.module,
                    "qualname": self.qualname,
                    "source_sha256": self.source_sha256,
                    "resolution_digest": self.resolution.resolution_digest,
                }
            ),
        )

    @property
    def benchmark_id(self) -> str:
        return self.resolution.task_set.benchmark_id


@dataclass(frozen=True, slots=True)
class RepositoryBenchmarkDiscoveryFailure:
    benchmark_package: str
    module: str
    qualname: str | None
    stage: str
    error_type: str
    error_message: str
    failure_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name, value in (
            ("benchmark_package", self.benchmark_package),
            ("module", self.module),
            ("stage", self.stage),
            ("error_type", self.error_type),
        ):
            if type(value) is not str or not value.strip() or value != value.strip():
                raise ValueError(
                    f"benchmark discovery failure {field_name} must be canonical text"
                )
        if self.qualname is not None and (
            type(self.qualname) is not str
            or not self.qualname.strip()
            or self.qualname != self.qualname.strip()
        ):
            raise ValueError(
                "benchmark discovery failure qualname must be canonical text"
            )
        if type(self.error_message) is not str:
            raise TypeError("benchmark discovery failure error_message must be text")
        object.__setattr__(
            self,
            "failure_digest",
            canonical_digest(
                {
                    "benchmark_package": self.benchmark_package,
                    "module": self.module,
                    "qualname": self.qualname,
                    "stage": self.stage,
                    "error_type": self.error_type,
                    "error_message": self.error_message,
                }
            ),
        )


def _resolution_return_type(value) -> bool:
    try:
        hints = get_type_hints(value)
    except (NameError, TypeError):
        return False
    return hints.get("return") is BenchmarkSourceResolution


def _source_digest(value) -> str:
    source_file = inspect.getsourcefile(value)
    if source_file is None:
        raise ValueError("benchmark authority callable has no Python source file")
    path = Path(source_file)
    if not path.is_file() or path.is_symlink():
        raise ValueError(
            "benchmark authority callable source must be a real Python file"
        )
    digest, _size = sha256_file(path)
    return digest


def discover_repository_benchmark_bindings() -> tuple[
    tuple[RepositoryBenchmarkBinding, ...],
    tuple[RepositoryBenchmarkDiscoveryFailure, ...],
]:
    """Discover exact source-contained benchmark authorities without heuristics."""

    root = Path(__file__).resolve().parents[1] / "benchmarks"
    if not root.is_dir():
        raise RuntimeError("repository benchmark root is missing")

    bindings: list[RepositoryBenchmarkBinding] = []
    failures: list[RepositoryBenchmarkDiscoveryFailure] = []

    for package_dir in sorted(root.iterdir(), key=lambda path: path.name):
        if (
            not package_dir.is_dir()
            or package_dir.is_symlink()
            or not (package_dir / "__init__.py").is_file()
        ):
            continue
        package = package_dir.name
        module_name = f"research.benchmarks.{package}"
        try:
            module = importlib.import_module(module_name)
        except BaseException as exc:
            failures.append(
                RepositoryBenchmarkDiscoveryFailure(
                    package,
                    module_name,
                    None,
                    "import",
                    type(exc).__name__,
                    str(exc),
                )
            )
            continue

        exported = getattr(module, "__all__", ())
        if type(exported) not in {tuple, list} or any(
            type(name) is not str or not name
            for name in exported
        ):
            failures.append(
                RepositoryBenchmarkDiscoveryFailure(
                    package,
                    module_name,
                    None,
                    "exports",
                    "TypeError",
                    "benchmark package __all__ must contain public text names",
                )
            )
            continue

        for name in exported:
            value = getattr(module, name, None)
            if not inspect.isfunction(value):
                continue
            try:
                signature = inspect.signature(value)
            except (TypeError, ValueError):
                continue
            if signature.parameters:
                continue
            if not _resolution_return_type(value):
                continue
            try:
                resolution = value()
                if type(resolution) is not BenchmarkSourceResolution:
                    raise TypeError(
                        "zero-argument benchmark authority returned wrong type"
                    )
                bindings.append(
                    RepositoryBenchmarkBinding(
                        package,
                        value.__module__,
                        value.__qualname__,
                        _source_digest(value),
                        resolution,
                    )
                )
            except BaseException as exc:
                failures.append(
                    RepositoryBenchmarkDiscoveryFailure(
                        package,
                        value.__module__,
                        value.__qualname__,
                        "resolve",
                        type(exc).__name__,
                        str(exc),
                    )
                )

    ordered_bindings = tuple(
        sorted(
            bindings,
            key=lambda row: (
                row.benchmark_id,
                row.benchmark_package,
                row.module,
                row.qualname,
                row.binding_digest,
            ),
        )
    )
    binding_keys = tuple(
        (row.module, row.qualname, row.binding_digest)
        for row in ordered_bindings
    )
    if len(binding_keys) != len(set(binding_keys)):
        raise RuntimeError("repository benchmark authority bindings are duplicated")

    ordered_failures = tuple(
        sorted(
            failures,
            key=lambda row: (
                row.benchmark_package,
                row.module,
                "" if row.qualname is None else row.qualname,
                row.stage,
                row.failure_digest,
            ),
        )
    )
    return ordered_bindings, ordered_failures


class RepositoryBenchmarkAuthority:
    """Fail-closed benchmark resolver over exact repository-owned cuts."""

    def __init__(
        self,
        bindings: tuple[RepositoryBenchmarkBinding, ...],
        failures: tuple[RepositoryBenchmarkDiscoveryFailure, ...] = (),
    ) -> None:
        if type(bindings) is not tuple or any(
            type(row) is not RepositoryBenchmarkBinding for row in bindings
        ):
            raise TypeError(
                "repository benchmark authority bindings must be typed tuple"
            )
        if type(failures) is not tuple or any(
            type(row) is not RepositoryBenchmarkDiscoveryFailure
            for row in failures
        ):
            raise TypeError(
                "repository benchmark authority failures must be typed tuple"
            )
        self._bindings = tuple(
            sorted(
                bindings,
                key=lambda row: (
                    row.benchmark_id,
                    row.binding_digest,
                ),
            )
        )
        self._failures = tuple(
            sorted(failures, key=lambda row: row.failure_digest)
        )
        self._authority_digest = canonical_digest(
            {
                "schema": "noetrium.repository-benchmark-authority.v1",
                "bindings": tuple(row.binding_digest for row in self._bindings),
                "discovery_failures": tuple(
                    row.failure_digest for row in self._failures
                ),
            }
        )

    @classmethod
    def discover(cls) -> "RepositoryBenchmarkAuthority":
        bindings, failures = discover_repository_benchmark_bindings()
        return cls(bindings, failures)

    @property
    def authority_digest(self) -> str:
        return self._authority_digest

    @property
    def bindings(self) -> tuple[RepositoryBenchmarkBinding, ...]:
        return self._bindings

    @property
    def failures(self) -> tuple[RepositoryBenchmarkDiscoveryFailure, ...]:
        return self._failures

    @property
    def benchmark_ids(self) -> tuple[str, ...]:
        return tuple(sorted({row.benchmark_id for row in self._bindings}))

    def _binding(self, benchmark_id: str) -> RepositoryBenchmarkBinding:
        matches = tuple(
            row for row in self._bindings if row.benchmark_id == benchmark_id
        )
        if not matches:
            raise ReproductionResearchOSCompileError(
                f"benchmark {benchmark_id!r} has no exact source-contained "
                "repository authority; immutable data/materialization is required"
            )
        if len(matches) != 1:
            raise ReproductionResearchOSCompileError(
                f"benchmark {benchmark_id!r} has ambiguous repository authorities: "
                f"{tuple((row.module, row.qualname) for row in matches)}"
            )
        return matches[0]

    def resolve(
        self,
        definition: ReproductionDefinition,
        study_factory: ReproductionStudyFactoryBinding,
    ) -> tuple[ReproductionBenchmarkSelection, ...]:
        if type(definition) is not ReproductionDefinition:
            raise TypeError(
                "repository benchmark resolution requires ReproductionDefinition"
            )
        if type(study_factory) is not ReproductionStudyFactoryBinding:
            raise TypeError(
                "repository benchmark resolution requires Study factory binding"
            )
        if study_factory.package != definition.package:
            raise ValueError(
                "repository benchmark resolution Study factory package drifted"
            )

        factories = resolve_study_factory_bindings(definition)
        if study_factory.qualname not in {row.qualname for row in factories}:
            raise ValueError(
                "repository benchmark resolution Study factory no longer resolves"
            )
        benchmark_ids = definition.catalog.benchmark_ids
        if len(benchmark_ids) > 1 and len(factories) > 1:
            raise ReproductionResearchOSCompileError(
                f"{definition.package} has multiple Study factories and multiple "
                "benchmarks; exact Study-to-benchmark ownership must be paper-owned"
            )

        split_consumers = set(resolve_benchmark_split_consumers(definition))
        split_aware = (
            f"study:{study_factory.qualname}" in split_consumers
            or any(
                consumer.startswith("method:")
                for consumer in split_consumers
            )
        )

        selections: list[ReproductionBenchmarkSelection] = []
        for benchmark_id in benchmark_ids:
            binding = self._binding(benchmark_id)
            task_set = binding.resolution.task_set
            if split_aware:
                if len(task_set.splits) != 1:
                    raise ReproductionResearchOSCompileError(
                        f"{definition.package} Study {study_factory.qualname} "
                        f"requires paper-owned split selection for benchmark "
                        f"{benchmark_id!r}; available="
                        f"{tuple(row.split_id for row in task_set.splits)}"
                    )
                split_ids = (task_set.splits[0].split_id,)
            else:
                split_ids = ()

            proof_digest = canonical_digest(
                {
                    "schema": "noetrium.repository-benchmark-selection-proof.v1",
                    "authority_digest": self._authority_digest,
                    "binding_digest": binding.binding_digest,
                    "resolution_digest": binding.resolution.resolution_digest,
                    "benchmark_cut_digest": task_set.cut_digest,
                    "benchmark_split_ids": split_ids,
                    "reproduction_definition_digest": definition.definition_digest,
                    "study_factory_binding_digest": study_factory.binding_digest,
                }
            )
            selections.append(
                ReproductionBenchmarkSelection(
                    task_set,
                    split_ids,
                    proof_digest,
                )
            )
        return tuple(
            sorted(selections, key=lambda row: row.selection_digest)
        )

    def audit_document(self) -> dict[str, object]:
        counts: dict[str, int] = {}
        for row in self._bindings:
            counts[row.benchmark_id] = counts.get(row.benchmark_id, 0) + 1
        return {
            "schema": "noetrium.repository-benchmark-authority-audit.v1",
            "authority_digest": self._authority_digest,
            "binding_count": len(self._bindings),
            "benchmark_ids": self.benchmark_ids,
            "ambiguous_benchmark_ids": tuple(
                sorted(
                    benchmark_id
                    for benchmark_id, count in counts.items()
                    if count != 1
                )
            ),
            "discovery_failure_count": len(self._failures),
            "discovery_failures": tuple(
                {
                    "benchmark_package": row.benchmark_package,
                    "module": row.module,
                    "qualname": row.qualname,
                    "stage": row.stage,
                    "error_type": row.error_type,
                    "error_message": row.error_message,
                    "failure_digest": row.failure_digest,
                }
                for row in self._failures
            ),
        }


__all__ = [
    "RepositoryBenchmarkAuthority",
    "RepositoryBenchmarkBinding",
    "RepositoryBenchmarkDiscoveryFailure",
    "discover_repository_benchmark_bindings",
]

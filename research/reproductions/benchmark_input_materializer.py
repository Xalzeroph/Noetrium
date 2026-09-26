"""Materialize repository benchmark authority from explicit machine-local facts.

Benchmark packages own their scientific/source validation. This module only
discovers the standard repository materialization entrypoint and aggregates its
proof-backed registrations into the canonical BenchmarkResolutionRegistry.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from noetrium_platform.composition.research_authority_inputs import (
    normalize_authority_inputs,
)
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    BenchmarkResolutionRegistration,
    BenchmarkResolutionRegistry,
)

_ENTRYPOINT = "materialize_repository_benchmark_authority"


def materialize_repository_benchmark_inputs(
    authority_inputs: tuple[tuple[str, str], ...],
) -> BenchmarkResolutionRegistry:
    """Materialize every benchmark whose exact required inputs are present."""

    frozen_inputs = normalize_authority_inputs(
        authority_inputs,
        label="repository benchmark authority_inputs",
    )
    root = Path(__file__).resolve().parents[1] / "benchmarks"
    registrations: list[BenchmarkResolutionRegistration] = []

    for package_dir in sorted(root.iterdir(), key=lambda path: path.name):
        if (
            not package_dir.is_dir()
            or package_dir.is_symlink()
            or not (package_dir / "materializer.py").is_file()
        ):
            continue
        module = importlib.import_module(
            f"research.benchmarks.{package_dir.name}.materializer"
        )
        factory = getattr(module, _ENTRYPOINT, None)
        if factory is None:
            continue
        if not callable(factory):
            raise TypeError(
                f"{module.__name__}.{_ENTRYPOINT} must be callable"
            )
        rows = factory(frozen_inputs)
        if type(rows) is not tuple or any(
            type(row) is not BenchmarkResolutionRegistration for row in rows
        ):
            raise TypeError(
                f"{module.__name__}.{_ENTRYPOINT} must return an immutable "
                "BenchmarkResolutionRegistration tuple"
            )
        registrations.extend(rows)

    return BenchmarkResolutionRegistry(tuple(registrations))


__all__ = ["materialize_repository_benchmark_inputs"]

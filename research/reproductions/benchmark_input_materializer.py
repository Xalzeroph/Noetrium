"""Materialize repository benchmark authority from explicit machine-local facts.

Benchmark packages own their scientific/source validation. This module only
discovers the standard repository materialization entrypoint and aggregates its
proof-backed registrations into the canonical BenchmarkResolutionRegistry.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Mapping
from pathlib import Path

from noetrium_platform.composition.research_authority_inputs import (
    normalize_authority_inputs,
)
from noetrium_platform.composition.research_execution_content import (
    ResearchExecutionContentAuthorities,
)
from noetrium_platform.foundation.kernel.kernel import JsonValue, freeze_json
from noetrium_platform.research.experimentation.lifecycle.api import (
    ExperimentTaskSpec,
    ResearchStudyDefinition,
    TaskVerifierPort,
)
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    BenchmarkResolutionRegistration,
    BenchmarkResolutionRegistry,
)
from noetrium_platform.research.experimentation.workload.api import (
    StaticExperimentTaskProjection,
)
from research.benchmarks.contracts import RepositoryBenchmarkTaskProjectionSpec

_ENTRYPOINT = "materialize_repository_benchmark_authority"
_PROJECTION_ENTRYPOINT = "repository_task_projection_spec"
_VERIFIER_ENTRYPOINT = "materialize_repository_task_verifier"


def _benchmark_materializer_modules() -> tuple[object, ...]:
    root = Path(__file__).resolve().parents[1] / "benchmarks"
    modules: list[object] = []
    for package_dir in sorted(root.iterdir(), key=lambda path: path.name):
        if (
            not package_dir.is_dir()
            or package_dir.is_symlink()
            or not (package_dir / "materializer.py").is_file()
        ):
            continue
        modules.append(
            importlib.import_module(
                f"research.benchmarks.{package_dir.name}.materializer"
            )
        )
    return tuple(modules)


def repository_benchmark_task_projection_specs(
) -> tuple[RepositoryBenchmarkTaskProjectionSpec, ...]:
    rows: list[RepositoryBenchmarkTaskProjectionSpec] = []
    for module in _benchmark_materializer_modules():
        factory = getattr(module, _PROJECTION_ENTRYPOINT, None)
        if factory is None:
            continue
        if not callable(factory):
            raise TypeError(
                f"{module.__name__}.{_PROJECTION_ENTRYPOINT} must be callable"
            )
        row = factory()
        if type(row) is not RepositoryBenchmarkTaskProjectionSpec:
            raise TypeError(
                f"{module.__name__}.{_PROJECTION_ENTRYPOINT} must return "
                "RepositoryBenchmarkTaskProjectionSpec"
            )
        rows.append(row)
    ordered = tuple(sorted(rows, key=lambda row: (row.benchmark_id, row.task_schema_id)))
    keys = tuple((row.benchmark_id, row.task_schema_id) for row in ordered)
    if len(keys) != len(set(keys)):
        raise ValueError("repository benchmark task projection specs must be unique")
    return ordered


def _document_path(document: Mapping[str, object], path: str) -> JsonValue:
    value: object = document
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise KeyError(f"benchmark task content path is missing: {path}")
        value = value[part]
    return freeze_json(value)


def materialize_repository_trial_task_projection(
    study: ResearchStudyDefinition,
    *,
    content: ResearchExecutionContentAuthorities,
) -> StaticExperimentTaskProjection:
    """Project immutable benchmark content into the one Trial task lookup."""

    if type(study) is not ResearchStudyDefinition:
        raise TypeError("repository Trial task projection requires ResearchStudyDefinition")
    if type(content) is not ResearchExecutionContentAuthorities:
        raise TypeError(
            "repository Trial task projection requires "
            "ResearchExecutionContentAuthorities"
        )
    matches = tuple(
        row
        for row in repository_benchmark_task_projection_specs()
        if row.benchmark_id == study.benchmark.benchmark_id
        and row.task_schema_id == study.benchmark.task_schema_id
    )
    if len(matches) != 1:
        raise KeyError(
            "no unique repository benchmark task projection for "
            f"{study.benchmark.benchmark_id}:{study.benchmark.task_schema_id}"
        )
    spec = matches[0]
    budget = study.execution_policy.trial_budget
    max_steps = 12 if budget.max_steps is None else budget.max_steps
    max_seconds = (
        budget.max_seconds
        if budget.max_seconds is not None
        else (budget.max_working_seconds or 180.0)
    )

    projected: list[ExperimentTaskSpec] = []
    for definition in study.benchmark.selected_tasks(study.benchmark_split_id):
        reference = definition.content_reference
        if reference is None:
            raise ValueError(
                f"benchmark task {definition.task_id!r} has no immutable content reference"
            )
        definition.verify_content(content.references, content.artifacts)
        try:
            decoded = json.loads(content.read(reference).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"benchmark task {definition.task_id!r} content is not canonical JSON"
            ) from exc
        if not isinstance(decoded, Mapping):
            raise TypeError(
                f"benchmark task {definition.task_id!r} content must be a JSON object"
            )
        objective = _document_path(decoded, spec.objective_path)
        if type(objective) is not str or not objective.strip():
            raise ValueError(
                f"benchmark task {definition.task_id!r} objective must be non-empty text"
            )
        context_value = ((
            ""
            if spec.context_path is None
            else _document_path(decoded, spec.context_path)
        ))
        if type(context_value) is not str:
            raise TypeError(
                f"benchmark task {definition.task_id!r} context must be text"
            )
        payload = {
            output_name: _document_path(decoded, source_path)
            for output_name, source_path in spec.payload_fields
        }
        projected.append(
            ExperimentTaskSpec(
                task_id=definition.task_id,
                family=definition.family,
                objective=objective,
                context=context_value,
                lineage_id=definition.task_digest,
                max_steps=max_steps,
                max_seconds=float(max_seconds),
                payload=payload,
            )
        )
    return StaticExperimentTaskProjection(tuple(projected))


def materialize_repository_task_verifier(
    study: ResearchStudyDefinition,
    *,
    content: ResearchExecutionContentAuthorities,
) -> TaskVerifierPort | None:
    """Resolve one benchmark-owned verifier through the repository convention."""

    if type(study) is not ResearchStudyDefinition:
        raise TypeError("repository task verifier requires ResearchStudyDefinition")
    if type(content) is not ResearchExecutionContentAuthorities:
        raise TypeError(
            "repository task verifier requires ResearchExecutionContentAuthorities"
        )
    verifier_ids = tuple(sorted({
        package.verifier_requirement_id
        for task in study.benchmark.selected_tasks(study.benchmark_split_id)
        if (package := task.package) is not None
        and package.verifier_requirement_id is not None
    }))
    if not verifier_ids:
        return None
    if len(verifier_ids) != 1:
        raise ValueError(
            "one Study cut must select exactly one benchmark verifier authority"
        )

    modules: list[object] = []
    for module in _benchmark_materializer_modules():
        projection_factory = getattr(module, _PROJECTION_ENTRYPOINT, None)
        if projection_factory is None:
            continue
        if not callable(projection_factory):
            raise TypeError(
                f"{module.__name__}.{_PROJECTION_ENTRYPOINT} must be callable"
            )
        spec = projection_factory()
        if type(spec) is not RepositoryBenchmarkTaskProjectionSpec:
            raise TypeError(
                f"{module.__name__}.{_PROJECTION_ENTRYPOINT} returned invalid spec"
            )
        if (
            spec.benchmark_id == study.benchmark.benchmark_id
            and spec.task_schema_id == study.benchmark.task_schema_id
        ):
            modules.append(module)
    if len(modules) != 1:
        raise LookupError(
            "no unique repository benchmark module for verifier "
            f"{study.benchmark.benchmark_id}:{study.benchmark.task_schema_id}"
        )
    module = modules[0]
    factory = getattr(module, _VERIFIER_ENTRYPOINT, None)
    if not callable(factory):
        raise LookupError(
            f"{module.__name__} does not materialize its declared task verifier"
        )
    verifier = factory(study, content=content)
    if not callable(getattr(verifier, "verify", None)):
        raise TypeError(
            f"{module.__name__}.{_VERIFIER_ENTRYPOINT} must return TaskVerifierPort"
        )
    identity = getattr(verifier, "identity_digest", None)
    if (
        type(identity) is not str
        or len(identity) != 64
        or any(ch not in "0123456789abcdef" for ch in identity)
    ):
        raise TypeError("repository task verifier identity_digest must be SHA-256")
    return verifier


def materialize_repository_benchmark_inputs(
    authority_inputs: tuple[tuple[str, str], ...],
    *,
    content: ResearchExecutionContentAuthorities,
) -> BenchmarkResolutionRegistry:
    """Materialize exact Benchmark cuts into the shared immutable content authority."""

    if type(content) is not ResearchExecutionContentAuthorities:
        raise TypeError(
            "repository benchmark materialization requires "
            "ResearchExecutionContentAuthorities"
        )
    frozen_inputs = normalize_authority_inputs(
        authority_inputs,
        label="repository benchmark authority_inputs",
    )
    registrations: list[BenchmarkResolutionRegistration] = []

    for module in _benchmark_materializer_modules():
        factory = getattr(module, _ENTRYPOINT, None)
        if factory is None:
            continue
        if not callable(factory):
            raise TypeError(
                f"{module.__name__}.{_ENTRYPOINT} must be callable"
            )
        rows = factory(frozen_inputs, content=content)
        if type(rows) is not tuple or any(
            type(row) is not BenchmarkResolutionRegistration for row in rows
        ):
            raise TypeError(
                f"{module.__name__}.{_ENTRYPOINT} must return an immutable "
                "BenchmarkResolutionRegistration tuple"
            )
        registrations.extend(rows)

    return BenchmarkResolutionRegistry(tuple(registrations))


__all__ = [
    "materialize_repository_benchmark_inputs",
    "materialize_repository_task_verifier",
    "materialize_repository_trial_task_projection",
    "repository_benchmark_task_projection_specs",
]

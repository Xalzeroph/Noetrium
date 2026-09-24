from __future__ import annotations

import research.reproductions.fleet as fleet_module
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.lifecycle.api import (
    BenchmarkTaskSet,
    TaskDefinition,
    TaskSetSplit,
)
from research.reproductions.adaptagent_acl2025.definition import (
    REPRODUCTION as ADAPTAGENT,
)
from research.reproductions.fleet import (
    ReproductionBenchmarkSelection,
    materialize_repository_execution_fleet,
    resolve_repository_execution_requests,
)
from research.reproductions.research_os import (
    executable_reproduction_definitions,
    resolve_benchmark_split_consumers,
)


def _benchmark(
    benchmark_id: str,
    *,
    split_aware: bool,
    split_id: str = "paper-eval",
) -> BenchmarkTaskSet:
    revision_id = "fleet-admission"
    task_id = f"{benchmark_id}.task"
    task = TaskDefinition(
        task_id,
        revision_id,
        "fleet-admission",
        f"{benchmark_id}.task.v1",
        canonical_digest(
            {
                "benchmark_id": benchmark_id,
                "revision_id": revision_id,
                "task_id": task_id,
            }
        ),
    )
    return BenchmarkTaskSet(
        benchmark_id=benchmark_id,
        revision_id=revision_id,
        source_digest=canonical_digest(
            {"benchmark_id": benchmark_id, "revision_id": revision_id}
        ),
        task_schema_id=f"{benchmark_id}.task.v1",
        tasks=(task,),
        splits=(
            (TaskSetSplit(split_id, (task_id,)),)
            if split_aware
            else ()
        ),
    )


class _StructuralBenchmarkResolver:
    """Synthetic authority used only to pressure the fleet compiler in CI."""

    def resolve(self, definition, study_factory):
        split_consumers = set(resolve_benchmark_split_consumers(definition))
        split_aware = (
            f"study:{study_factory.qualname}" in split_consumers
            or any(
                consumer.startswith("method:")
                for consumer in split_consumers
            )
        )
        return tuple(
            ReproductionBenchmarkSelection(
                _benchmark(benchmark_id, split_aware=split_aware),
                ("paper-eval",) if split_aware else (),
                canonical_digest(
                    {
                        "authority": "ci.structural-benchmark-authority.v1",
                        "package": definition.package,
                        "study_factory": study_factory.qualname,
                        "benchmark_id": benchmark_id,
                    }
                ),
            )
            for benchmark_id in definition.catalog.benchmark_ids
        )


class _AdaptAgentBenchmarkResolver:
    def resolve(self, definition, study_factory):
        assert definition.package == "adaptagent_acl2025"
        assert study_factory.qualname == "build_adaptagent_study"
        return (
            ReproductionBenchmarkSelection(
                _benchmark(
                    "mind2web",
                    split_aware=True,
                    split_id="test",
                ),
                ("test",),
                canonical_digest(
                    {"authority": "test.adaptagent.mind2web.paper-cut"}
                ),
            ),
        )


def test_full_repository_execution_requests_close_every_catalog_benchmark() -> None:
    requests = resolve_repository_execution_requests(
        _StructuralBenchmarkResolver()
    )
    executable = executable_reproduction_definitions()

    assert requests
    assert len({row.request_digest for row in requests}) == len(requests)
    assert {row.package for row in requests} == {
        row.package for row in executable
    }

    by_package: dict[str, set[str]] = {}
    for request in requests:
        by_package.setdefault(request.package, set()).add(
            request.benchmark.benchmark_id
        )
        assert len(request.benchmark_resolution_proof_digest) == 64

    for definition in executable:
        assert by_package[definition.package] == set(
            definition.catalog.benchmark_ids
        )


def test_materialized_fleet_compiles_exact_study_and_bound_program(monkeypatch) -> None:
    monkeypatch.setattr(
        fleet_module,
        "executable_reproduction_definitions",
        lambda: (ADAPTAGENT,),
    )

    materialized = materialize_repository_execution_fleet(
        _AdaptAgentBenchmarkResolver()
    )

    assert len(materialized.requests) == 1
    assert len(materialized.lanes) == 1
    assert len(materialized.portfolio.programs) == 1
    lane = materialized.lanes[0]
    assert lane.definition.package == "adaptagent_acl2025"
    assert lane.binding.benchmark_split_id == "test"
    assert lane.study.benchmark_split_id == "test"
    assert lane.study.benchmark.cut_digest == lane.request.benchmark.cut_digest
    assert lane.program == materialized.portfolio.programs[0]
    assert len(lane.lane_digest) == 64
    assert len(materialized.materialization_digest) == 64

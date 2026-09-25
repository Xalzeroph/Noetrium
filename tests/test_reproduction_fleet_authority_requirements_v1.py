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
from research.reproductions.authority_requirements import (
    compile_materialized_fleet_owner_requirements,
    compile_repository_fleet_prerequisites,
)
from research.reproductions.fleet import (
    ReproductionBenchmarkSelection,
    materialize_repository_execution_fleet,
)
from research.reproductions.research_os import (
    executable_reproduction_definitions,
)


class _AdaptAgentBenchmarkResolver:
    authority_digest = canonical_digest(
        {"authority": "test.owner-requirements.adaptagent.v1"}
    )

    @staticmethod
    def _benchmark(benchmark_id: str) -> BenchmarkTaskSet:
        revision = "owner-requirement-fixture"
        task_id = benchmark_id + ".task"
        task = TaskDefinition(
            task_id,
            revision,
            "fixture",
            benchmark_id + ".task.v1",
            canonical_digest({"benchmark": benchmark_id, "task": task_id}),
        )
        return BenchmarkTaskSet(
            benchmark_id=benchmark_id,
            revision_id=revision,
            source_digest=canonical_digest(
                {"benchmark": benchmark_id, "revision": revision}
            ),
            task_schema_id=benchmark_id + ".task.v1",
            tasks=(task,),
            splits=(TaskSetSplit("test", (task_id,)),),
        )

    def resolve(self, definition, study_factory):
        assert definition.package == "adaptagent_acl2025"
        assert study_factory.qualname == "build_adaptagent_study"
        return tuple(
            ReproductionBenchmarkSelection(
                self._benchmark(benchmark_id),
                ("test",),
                canonical_digest(
                    {
                        "authority": self.authority_digest,
                        "benchmark_id": benchmark_id,
                    }
                ),
            )
            for benchmark_id in definition.catalog.benchmark_ids
        )


def test_prerequisite_manifest_covers_every_executable_reproduction() -> None:
    manifest = compile_repository_fleet_prerequisites()
    executable = executable_reproduction_definitions()

    assert len(manifest.manifest_digest) == 64
    assert {row.package for row in manifest.requirements} == {
        row.package for row in executable
    }
    assert {row.stage for row in manifest.requirements} <= {
        "benchmark",
        "reproduction_capability",
        "paper_option",
    }
    assert all(len(row.requirement_digest) == 64 for row in manifest.requirements)
    assert len({
        (row.package, row.stage, row.requirement_key)
        for row in manifest.requirements
    }) == len(manifest.requirements)


def test_materialized_owner_manifest_exports_only_owner_requirements(monkeypatch) -> None:
    monkeypatch.setattr(
        fleet_module,
        "executable_reproduction_definitions",
        lambda: (ADAPTAGENT,),
    )
    fleet = materialize_repository_execution_fleet(
        _AdaptAgentBenchmarkResolver()
    )
    manifest = compile_materialized_fleet_owner_requirements(fleet)

    assert manifest.materialization_digest == fleet.materialization_digest
    assert len(manifest.manifest_digest) == 64
    assert {row.stage for row in manifest.requirements} == {
        "project_manifest",
        "participant",
        "model",
        "trial_provider",
        "aggregation",
        "reconciliation",
    }
    assert {row.owner for row in manifest.requirements} == {
        "portfolio",
        "participant",
        "model",
        "experimentation",
    }

    by_program: dict[str, list] = {}
    for row in manifest.requirements:
        by_program.setdefault(row.program_id, []).append(row)
        assert row.package == "adaptagent_acl2025"
        assert len(row.requirement_digest) == 64

    assert set(by_program) == {
        row.program.program_id for row in fleet.lanes
    }
    for rows in by_program.values():
        assert sum(row.stage == "project_manifest" for row in rows) == 1
        assert sum(row.stage == "participant" for row in rows) == 1
        assert sum(row.stage == "model" for row in rows) == 1
        assert sum(row.stage == "trial_provider" for row in rows) == 1
        assert sum(row.stage == "aggregation" for row in rows) == 1
        assert sum(row.stage == "reconciliation" for row in rows) == 1


def test_owner_requirement_manifest_is_bound_to_materialization(monkeypatch) -> None:
    monkeypatch.setattr(
        fleet_module,
        "executable_reproduction_definitions",
        lambda: (ADAPTAGENT,),
    )
    first = materialize_repository_execution_fleet(
        _AdaptAgentBenchmarkResolver()
    )
    first_manifest = compile_materialized_fleet_owner_requirements(first)

    class _OtherResolver(_AdaptAgentBenchmarkResolver):
        authority_digest = canonical_digest(
            {"authority": "test.owner-requirements.adaptagent.v2"}
        )

    second = materialize_repository_execution_fleet(_OtherResolver())
    second_manifest = compile_materialized_fleet_owner_requirements(second)

    assert first.materialization_digest != second.materialization_digest
    assert first_manifest.manifest_digest != second_manifest.manifest_digest

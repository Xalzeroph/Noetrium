from __future__ import annotations

import pytest

from noetrium_platform.research.experimentation import (
    ComparisonRecord,
    ResearchPackage,
    ResearchRunRecord,
    fork_run,
)


def digest(label: str) -> str:
    from noetrium_platform.foundation.kernel.kernel import canonical_digest
    return canonical_digest({"label": label})


def make_run(run_id: str) -> ResearchRunRecord:
    return ResearchRunRecord(
        run_id=run_id,
        head_commit_id=digest(f"{run_id}:commit"),
        program_digest=digest(f"{run_id}:program"),
        binding_digest=digest(f"{run_id}:binding"),
        result_digest=digest(f"{run_id}:result"),
        status="completed",
    )


def test_package_round_trips_with_integrity() -> None:
    run_a = make_run("run-a")
    run_b = make_run("run-b")
    comparison = ComparisonRecord(
        comparison_id="comparison-1",
        run_ids=("run-a", "run-b"),
        evaluator_digest=digest("evaluator"),
        result_digest=digest("comparison-result"),
        status="complete",
    )
    fork = fork_run(
        source_run_id="run-a",
        source_commit_id=run_a.head_commit_id,
        new_run_id="run-c",
        change_digest=digest("change"),
    )
    package = ResearchPackage(
        package_id="package-1",
        definition_digest=digest("definition"),
        runs=(run_a, run_b),
        comparisons=(comparison,),
        forks=(fork,),
        dependency_digests=(digest("dependency"),),
    )
    restored = ResearchPackage.import_bytes(package.export_bytes())
    assert restored == package
    assert restored.package_digest == package.package_digest


def test_package_rejects_tampering() -> None:
    package = ResearchPackage(
        package_id="package-1",
        definition_digest=digest("definition"),
        runs=(make_run("run-a"),),
    )
    raw = package.export_bytes().replace(b'"status":"completed"', b'"status":"failed"', 1)
    with pytest.raises(ValueError):
        ResearchPackage.import_bytes(raw)


def test_fork_requires_new_identity() -> None:
    run = make_run("run-a")
    with pytest.raises(ValueError):
        fork_run(
            source_run_id="run-a",
            source_commit_id=run.head_commit_id,
            new_run_id="run-a",
            change_digest=digest("change"),
        )

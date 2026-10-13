from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.unit_codec import decode_unit, encode_unit
from noetrium_platform.research.experimentation.record import (
    build_research_package,
    comparison_record,
    fork_run,
    research_package_digest,
    research_package_forks,
    research_package_id,
    research_package_runs,
    research_run_record,
    run_record_value,
)


def digest(label: str) -> str:
    from noetrium_platform.foundation.kernel.kernel import canonical_digest
    return canonical_digest({"label": label})


def make_run(run_id: str) -> NoetriumUnit:
    return research_run_record(
        run_id=run_id,
        head_commit_id=digest(f"{run_id}:commit"),
        program_digest=digest(f"{run_id}:program"),
        program_lock_digest=digest(f"{run_id}:program-lock"),
        binding_digest=digest(f"{run_id}:binding"),
        result_digest=digest(f"{run_id}:result"),
        status="completed",
    )


def test_package_round_trips_with_one_unit_codec() -> None:
    run_a = make_run("run-a")
    run_b = make_run("run-b")
    comparison = comparison_record(
        comparison_id="comparison-1",
        run_ids=("run-a", "run-b"),
        evaluator_digest=digest("evaluator"),
        result_digest=digest("comparison-result"),
        status="complete",
    )
    fork = fork_run(
        source_run_id="run-a",
        source_commit_id=run_record_value(run_a, "head_commit_id"),
        new_run_id="run-c",
        change_digest=digest("change"),
    )
    package = build_research_package(
        package_id="package-1",
        definition=digest("definition"),
        runs=(run_a, run_b),
        comparisons=(comparison,),
        forks=(fork,),
        dependencies=(digest("dependency"),),
    )
    restored = decode_unit(encode_unit(package))
    assert type(restored) is NoetriumUnit
    assert restored == package
    assert research_package_id(restored) == "package-1"
    assert research_package_digest(restored) == restored.unit_digest
    assert research_package_runs(restored) == (run_a, run_b)
    assert research_package_forks(restored) == (fork,)


def test_package_codec_rejects_tampering() -> None:
    package = build_research_package(
        package_id="package-1",
        definition=digest("definition"),
        runs=(make_run("run-a"),),
    )
    raw = encode_unit(package).replace(b'"status":"completed"', b'"status":"failed"', 1)
    with pytest.raises(ValueError):
        decode_unit(raw)


def test_fork_requires_new_identity() -> None:
    run = make_run("run-a")
    with pytest.raises(ValueError):
        fork_run(
            source_run_id="run-a",
            source_commit_id=run_record_value(run, "head_commit_id"),
            new_run_id="run-a",
            change_digest=digest("change"),
        )

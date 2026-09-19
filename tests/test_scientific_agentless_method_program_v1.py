from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from research.benchmarks.swe_bench import (
    SWEBenchTaskRecord,
    build_swe_bench_task_set,
)
from research.reproductions.agentless_swebench import (
    AGENTLESS_FIDELITY,
    AGENTLESS_METHOD_PROGRAM,
    build_agentless_swebench_lite_study,
)


def _benchmark():
    rows = (
        SWEBenchTaskRecord(
            instance_id="repo__project-1",
            repo="repo/project",
            base_commit="a" * 40,
            split_id="test",
            content_digest=canonical_digest({"instance": 1}),
        ),
    )
    return build_swe_bench_task_set(
        rows,
        subset="lite",
        harness_commit="b" * 40,
        dataset_revision="test-fixture",
        dataset_content_sha256=canonical_digest({"dataset": "fixture"}),
    )


def test_agentless_preserves_fixed_non_autonomous_three_stage_semantics() -> None:
    assert AGENTLESS_FIDELITY.stages == (
        "localization",
        "repair",
        "patch_validation",
    )
    assert AGENTLESS_FIDELITY.autonomous_agent_loop is False
    assert AGENTLESS_FIDELITY.model_selects_next_tool_action is False
    assert AGENTLESS_METHOD_PROGRAM.configuration["autonomous_agent_loop"] is False
    assert AGENTLESS_METHOD_PROGRAM.required_capabilities == ("software.command",)


def test_agentless_swebench_study_is_bound_to_generic_swebench_authority() -> None:
    study = build_agentless_swebench_lite_study(_benchmark(), split_id="test")
    assert study.benchmark.benchmark_id == "swe-bench"
    assert study.method.implementation == "agentless-v1.5.0"
    assert tuple(
        row.measurement_id for row in study.measurement_protocol.definitions
    ) == ("task_resolved", "model_call_count", "validation_count")

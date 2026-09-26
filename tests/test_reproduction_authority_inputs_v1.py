from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.composition.managed_research_runtime import (
    ManagedResearchRuntime,
)
from noetrium_platform.composition.research_authority_inputs import (
    authority_input_value,
    normalize_authority_inputs,
)
from noetrium_platform.composition.research_execution_content import (
    compose_research_execution_content,
)
from research.benchmarks.gsm8k.materializer import (
    GSM8K_REPOSITORY_TEST_INPUT,
    materialize_repository_benchmark_authority,
)
from research.reproductions.benchmark_input_materializer import (
    materialize_repository_benchmark_inputs,
)
from noetrium_platform.composition.research_portfolio_execution import (
    ResearchExecutionContext,
)

ROOT = Path(__file__).resolve().parents[1]


def test_authority_inputs_are_sorted_unique_and_exact() -> None:
    frozen = normalize_authority_inputs(
        (("zeta", "/z"), ("alpha", "/a")),
        label="test authority inputs",
    )
    assert frozen == (("alpha", "/a"), ("zeta", "/z"))
    assert authority_input_value(frozen, "alpha") == "/a"
    assert authority_input_value(frozen, "missing") is None

    with pytest.raises(ValueError, match="keys must be unique"):
        normalize_authority_inputs(
            (("same", "one"), ("same", "two")),
            label="test authority inputs",
        )


def test_fleet_context_exposes_same_authority_input_contract_as_project_execution(
    tmp_path: Path,
) -> None:
    runtime = object.__new__(ManagedResearchRuntime)
    context = ResearchExecutionContext(
        tmp_path,
        runtime,
        authority_inputs=(("benchmark.gsm8k.test_jsonl", "/data/test.jsonl"),),
    )
    assert (
        context.authority_input("benchmark.gsm8k.test_jsonl")
        == "/data/test.jsonl"
    )
    assert context.authority_input("missing") is None
    assert context.content is not None
    assert context.content.root == (tmp_path / "content").absolute()


def test_repository_benchmark_materialization_is_zero_input_neutral(
    tmp_path: Path,
) -> None:
    content = compose_research_execution_content(tmp_path / "content")
    registry = materialize_repository_benchmark_inputs((), content=content)
    assert registry.registrations == ()
    assert registry.benchmark_ids == ()


def test_gsm8k_repository_materializer_is_fail_closed_on_wrong_asset(
    tmp_path: Path,
) -> None:
    wrong = tmp_path / "test.jsonl"
    wrong.write_text('{"question":"1+1?","answer":"#### 2"}\n', encoding="utf-8")
    content = compose_research_execution_content(tmp_path / "content")
    with pytest.raises(ValueError, match="Git blob identity mismatch"):
        materialize_repository_benchmark_authority(
            ((GSM8K_REPOSITORY_TEST_INPUT, str(wrong)),),
            content=content,
        )


def test_control_plane_authority_assets_are_explicit_read_only_mounts() -> None:
    bootstrap = (ROOT / "deploy" / "build-environments.sh").read_text(
        encoding="utf-8"
    )
    launcher = (ROOT / "deploy" / "noetrium").read_text(encoding="utf-8")

    assert "NOETRIUM_CONTROL_INPUT_ROOT" in bootstrap
    assert 'test ! -L "$CONTROL_INPUT_ROOT"' in bootstrap
    assert '-v "$CONTROL_INPUT_ROOT:$CONTROL_INPUT_ROOT:ro"' in bootstrap
    assert "NOETRIUM_CONTROL_INPUT_ROOT" in launcher
    assert "control_input_root_from_env_file" in launcher
    assert 'fleet "$@" --state-root "$FLEET_STATE_ROOT"' in launcher

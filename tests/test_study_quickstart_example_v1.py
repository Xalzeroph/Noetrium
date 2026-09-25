from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "quickstart_experiment_plan.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("noetrium_quickstart_example", EXAMPLE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_quickstart_example_builds_a_consistent_reproducible_plan() -> None:
    example = _load_example()
    first = example.build_plan()
    second = example.build_plan()
    first.assert_consistent()
    second.assert_consistent()
    assert first.protocol.study_id == "noetrium-quickstart"
    assert tuple(item.variant_id for item in first.protocol.variants) == ("control", "treatment")
    assert first.protocol_digest == second.protocol_digest
    assert first.plan_digest == second.plan_digest
    assert len(first.protocol_digest) == 64
    assert len(first.plan_digest) == 64

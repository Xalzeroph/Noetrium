from __future__ import annotations

from hashlib import sha256

from research.benchmarks.mind2web import Mind2WebTaskRecord, build_mind2web_task_set
from research.reproductions.cogagent import (
    COGAGENT_FIDELITY,
    COGAGENT_METHOD_PROGRAM,
    build_cogagent_mind2web_study,
    cogagent_initial_state,
)


def _benchmark():
    row = Mind2WebTaskRecord(
        annotation_id="mind2web:cogagent:001",
        website="example",
        domain="shopping",
        subdomain="product",
        split_id="test_task",
        content_digest=sha256(b"cogagent-mind2web-001").hexdigest(),
        step_count=1,
    )
    return build_mind2web_task_set(
        (row,),
        dataset_revision="paper-test-cut",
        dataset_content_sha256=sha256(b"mind2web-cogagent-cut").hexdigest(),
        require_paper_split_cardinality=False,
    )


def test_cogagent_fidelity_freezes_visual_gui_contract() -> None:
    assert COGAGENT_FIDELITY.model_parameters_billion == 18
    assert COGAGENT_FIDELITY.input_resolution == (1120, 1120)
    assert COGAGENT_FIDELITY.gui_input_representation == "screenshot_only"
    state = cogagent_initial_state(
        task_instruction="Click the checkout button",
        screenshot_ref="artifact:screenshot:001",
        candidates=({"candidate_id": "checkout"},),
    )
    assert state["candidates"] == ({"candidate_id": "checkout"},)
    assert "step_success_rate" in COGAGENT_METHOD_PROGRAM.metric_names


def test_cogagent_mind2web_study_is_protocol_bound() -> None:
    benchmark = _benchmark()
    study = build_cogagent_mind2web_study(
        benchmark,
        split_id="test_task",
    )
    assert study.benchmark.cut_digest == benchmark.cut_digest
    assert study.trial_protocol_identity.protocol_id == (
        "cogagent.cvpr2024.mind2web.v1"
    )
    assert tuple(
        row.measurement_id for row in study.measurement_protocol.definitions
    ) == ("step_success_rate", "model_call_count")

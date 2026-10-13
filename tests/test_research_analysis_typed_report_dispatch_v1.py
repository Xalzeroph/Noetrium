"""Paper-defined analysis Units receive evidence-backed report values by type."""
from types import SimpleNamespace
from unittest.mock import patch

from noetrium_platform.composition.research_runtime import (
    CanonicalResearchNodeRuntime,
)
from noetrium_platform.composition import research_scientific_analysis as scientific
from noetrium_platform.foundation.kernel.kernel import ExecutionContext


def _report_ref(artifact: str) -> dict:
    return {
        "schema": "research.experiment-report-ref.v4",
        "manifest": {"reference_id": artifact},
    }


def _materialized(artifact: str) -> dict:
    return {
        "schema": "research.analysis-input.v1",
        "measurement_rows": ({"measurement_id": artifact, "value": True},),
        "rows": (),
        "aggregates": (),
        "trial_receipts": (),
        "measurement_records": (),
        "input_digest": artifact,
    }


def test_unrelated_typed_unit_payload_is_exact_identity_preserving():
    sentinel = object()
    payload = {"method_state": {"value": 5}, "unrelated": ("a", "b")}
    with patch.object(scientific, "materialize_experiment_report_input") as materialize:
        observed = scientific.materialize_research_scientific_inputs(payload, sentinel)
    assert observed is payload
    materialize.assert_not_called()


def test_single_port_report_materializes_and_projects_measurements():
    authority = object()
    with patch.object(
        scientific, "materialize_experiment_report_input", return_value=_materialized("studyA")
    ) as materialize:
        observed = scientific.materialize_research_scientific_inputs(
            {"experiment_report": _report_ref("studyA"), "purpose": "extract architecture"},
            authority,
        )
    assert observed["experiment_report"]["schema"] == "research.analysis-input.v1"
    assert observed["measurement_rows"][0]["measurement_id"] == "studyA"
    assert observed["purpose"] == "extract architecture"
    materialize.assert_called_once()


def test_multiple_report_ports_remain_independent_and_identified():
    def load(report, _authority):
        return _materialized(report["manifest"]["reference_id"])

    with patch.object(scientific, "materialize_experiment_report_input", side_effect=load):
        observed = scientific.materialize_research_scientific_inputs(
            {"report_000": _report_ref("a"), "report_001": _report_ref("b")},
            object(),
        )
    assert observed["report_000"]["measurement_rows"][0]["measurement_id"] == "a"
    assert observed["report_001"]["measurement_rows"][0]["measurement_id"] == "b"
    assert "measurement_rows" not in observed


def test_research_analysis_executes_typed_materialization_without_engine_flag():
    # Simulates a paper-defined research.analysis Unit whose symbol parameters
    # do NOT contain the obsolete analysis_engine opt-in.
    runtime = object.__new__(CanonicalResearchNodeRuntime)
    runtime._content = object()
    node = SimpleNamespace(
        graph_node_id="paper:analysis",
        symbols=(SimpleNamespace(parameters={"analysis": {"kind": "paper_specific"}}),),
    )
    binding = SimpleNamespace(binding_digest="b" * 64, lowering_mode="unit")
    control = SimpleNamespace(checkpoint=lambda: None)
    inputs = {"experiment_report": _report_ref("studyA")}
    with (
        patch.object(CanonicalResearchNodeRuntime, "admit", return_value=SimpleNamespace(
            runtime_binding_digest="c" * 64,
        )),
        patch.object(CanonicalResearchNodeRuntime, "_machine_id", return_value="machine:x"),
        patch.object(CanonicalResearchNodeRuntime, "_execute_unit", return_value="executed") as execute,
        patch(
            "noetrium_platform.composition.research_runtime.materialize_research_scientific_inputs",
            return_value={"experiment_report": _materialized("studyA")},
        ) as materialize,
    ):
        result = runtime.execute(
            ExecutionContext("run", "trace", "span"),
            control,
            node,
            binding,
            inputs,
            execution_cut_id="d" * 64,
            deadline=None,
        )
    assert result == "executed"
    materialize.assert_called_once_with(inputs, runtime._content)
    assert execute.call_args.args[4]["experiment_report"]["schema"] == "research.analysis-input.v1"

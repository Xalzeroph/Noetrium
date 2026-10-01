from __future__ import annotations

import base64
from types import SimpleNamespace

import noetrium.api as api

from noetrium_platform.composition.research_os_scientific_analysis import (
    compile_declarative_analysis_program,
    compile_declarative_metric_program,
)
from noetrium_platform.composition.research_os_study_closure import (
    research_measurement_definitions,
)
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    MeasurementDefinition,
    MeasurementValueKind,
)
from noetrium_platform.research.experimentation.lifecycle.study.providers.trial import (
    StandardWorkloadMeasurementProjection,
)
from noetrium_platform.research.experimentation.workbench.api import (
    DataColumn,
    DataTable,
    MultipleComparisonMethod,
)
from noetrium_platform.research.experimentation.workbench.runtime import (
    ScientificStatistics,
)


def _program():
    portfolio = api.ResearchPortfolioBuilder("metrics-v2")
    builder = portfolio.program("paper")
    builder.metric(
        "architecture-matrix",
        value_kind="matrix",
        schema_id="architecture.matrix.v1",
        semantic_kind="architecture",
        source_path="diagnostics.architecture_matrix",
        reducer="last",
        description="Frozen architecture distance matrix.",
    )
    builder.metric(
        "latency-mean",
        aggregation="mean",
        record_types=("llm.usage",),
        value_path="latency_ms",
        group_by=("model",),
        unit="ms",
    )
    builder.evaluation(
        "derive-latency",
        definitions=("latency-mean",),
        outputs=(("metric-values", "metric"),),
    )
    builder.analysis(
        "compare-latency",
        depends_on=("derive-latency",),
        value="value",
        group_by=("model",),
        comparison_group="model",
        baseline="a",
        candidate="b",
        inference="group_compare",
        outputs=(("claim-evidence", "evidence"),),
    )
    return portfolio.freeze().programs[0]


def _raw(sequence: int, model: str, latency: float) -> dict:
    raw=f'{{"model":"{model}","latency_ms":{latency}}}'.encode()
    return {
        "experiment_id":"exp",
        "run_id":"run",
        "unit_id":f"unit-{sequence}",
        "sequence":sequence,
        "occurred_at":"2026-09-30T00:00:00Z",
        "recorded_at":"2026-09-30T00:00:01Z",
        "producer_id":"fixture",
        "schema_id":"llm.usage.v1",
        "record_type":"llm.usage",
        "raw_payload_b64":base64.b64encode(raw).decode(),
        "payload":{"model":model,"latency_ms":latency},
    }


def test_public_api_remains_exactly_four_roots():
    assert api.__all__ == (
        "ResearchPortfolioBuilder",
        "ResearchPortfolio",
        "ResearchOS",
        "open_project",
    )


def test_top_level_metric_projects_typed_measurement_without_internal_imports():
    program=_program()
    rows=research_measurement_definitions(program.definitions)
    assert len(rows)==1
    row=rows[0]
    assert row.measurement_id=="architecture-matrix"
    assert row.value_kind.value=="matrix"
    assert row.source_path=="diagnostics.architecture_matrix"
    assert row.reducer=="last"


def test_declarative_raw_metric_executes_existing_metric_engine():
    program=_program()
    definition=next(row for row in program.definitions if row.definition_id=="latency-mean")
    machine,operations=compile_declarative_metric_program(definition)
    assert machine.kind.value=="evaluation"
    result=operations[0].handler(
        SimpleNamespace(payload={
            "raw_records":(
                _raw(0,"a",100.0),
                _raw(1,"a",200.0),
                _raw(2,"b",50.0),
            )
        }),
        None,
    )
    values={row["group"]["model"]:row["value"] for row in result.value["values"]}
    assert values=={"a":150.0,"b":50.0}


def test_declarative_analysis_executes_existing_workbench_statistics():
    program=_program()
    definition=next(
        row for row in program.definitions
        if row.definition_id=="compare-latency.analysis"
    )
    machine,operations=compile_declarative_analysis_program(definition)
    assert machine.kind.value=="analysis"
    result=operations[0].handler(
        SimpleNamespace(payload={
            "rows":(
                {"model":"a","value":1.0},
                {"model":"a","value":3.0},
                {"model":"b","value":4.0},
                {"model":"b","value":8.0},
            )
        }),
        None,
    )
    assert result.value["inference_method"]=="group_compare"
    assert result.value["inference"]["difference"]==4.0
    assert result.value["table_digest"]
    assert result.value["analysis_result_digest"]


def test_compare_many_accepts_declared_multiplicity_policy():
    table=DataTable(
        "scores",
        (
            DataColumn("method","text",False),
            DataColumn("score","float",False),
        ),
        (
            ("control",1.0),
            ("control",2.0),
            ("a",3.0),
            ("a",4.0),
            ("b",5.0),
            ("b",6.0),
        ),
    )
    results=ScientificStatistics().compare_many(
        table,
        "score",
        "method",
        baseline="control",
        candidates=("a","b"),
        correction=MultipleComparisonMethod.BONFERRONI,
        alpha=0.01,
    )
    assert len(results)==2
    assert all(row.adjusted_p_value is not None for row in results)


def test_analysis_definition_is_downstream_scientific_definition_not_new_root():
    program=_program()
    definition=next(
        row for row in program.definitions
        if row.definition_id=="compare-latency.analysis"
    )
    assert definition.kind.value=="analysis"
    assert definition.config["analysis_engine"]=="workbench"
    assert definition.config["analysis"]["inference"]=="group_compare"


def test_derived_metric_unit_does_not_accidentally_register_study_measurement():
    program=_program()
    rows=research_measurement_definitions(program.definitions)
    assert tuple(row.measurement_id for row in rows)==("architecture-matrix",)


def test_standard_projection_supports_non_scalar_typed_measurements():
    projection=StandardWorkloadMeasurementProjection()
    cases=(
        (MeasurementValueKind.CATEGORICAL,"label","label"),
        (MeasurementValueKind.STRUCTURED,{"nodes":3},{"nodes":3}),
        (MeasurementValueKind.SEQUENCE,("a","b"),("a","b")),
        (
            MeasurementValueKind.DISTRIBUTION,
            ((1.0,0.25),(2.0,0.75)),
            ((1.0,0.25),(2.0,0.75)),
        ),
        (
            MeasurementValueKind.MATRIX,
            ((1.0,2.0),(3.0,4.0)),
            ((1.0,2.0),(3.0,4.0)),
        ),
        (MeasurementValueKind.TEXT_JUDGEMENT,"grounded","grounded"),
    )
    for kind, raw, expected in cases:
        definition=MeasurementDefinition(
            measurement_id=f"m-{kind.value}",
            schema_id=f"{kind.value}.v1",
            value_kind=kind,
            source_path="diagnostics.value",
            reducer="last",
        )
        value=projection._declared_value(
            definition,
            (SimpleNamespace(diagnostics={"value":raw}),),
        )
        assert value.kind is kind
        carrier={
            MeasurementValueKind.CATEGORICAL:value.categorical,
            MeasurementValueKind.STRUCTURED:value.structured,
            MeasurementValueKind.SEQUENCE:value.sequence,
            MeasurementValueKind.DISTRIBUTION:value.distribution,
            MeasurementValueKind.MATRIX:value.matrix,
            MeasurementValueKind.TEXT_JUDGEMENT:value.text_judgement,
        }[kind]
        assert carrier==expected

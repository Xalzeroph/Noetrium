from __future__ import annotations

import base64
import hashlib
import tempfile
from pathlib import Path

from noetrium.contracts.research import (
    AggregationFunction, AggregationSpec, BaselineSpec, DataColumn, DataTable,
    EvaluationContext, EvaluationStage, FigureCell, FigureKind, FigureOutputFormat, FigurePoint,
    FigureSeries, FigureSpec, FigureStyle, MissingValuePolicy, MultipleComparisonMethod,
    ResearchFigureFactory, ResearchLifecycle, ScientificStatistics, SplitStrategy, StandardTableRenderer,
    PdfFigureRenderer, PublicationFigureRenderer, StudyObservationTableAdapter,
    SvgFigureRenderer, TablePipeline,
)
from noetrium_platform.research.experimentation.identity import OptionalIdentityFacet
from noetrium_platform.research.experimentation.workbench.providers import CsvTableReader
from noetrium_platform.research.experimentation.study.api import (
    MeasurementRecord, MeasurementValue, MeasurementValueKind,
    StudyAssignment, StudyMetricObservation,
)


SHA_A = "a" * 64
SHA_B = "b" * 64


def _table() -> DataTable:
    return DataTable(
        "scores",
        (DataColumn("variant", "text", False), DataColumn("score", "float", False), DataColumn("step", "int", False)),
        (("control", 1.0, 0), ("control", 3.0, 1), ("treatment", 4.0, 0), ("treatment", 8.0, 1)),
        source_digest=SHA_A,
    )


def test_table_is_immutable_and_binds_schema_rows_and_lineage():
    table = _table()
    assert table.column_names == ("variant", "score", "step")
    assert table.values("score") == (1.0, 3.0, 4.0, 8.0)
    assert len(table.table_digest) == 64


def test_pipeline_transforms_require_configuration_and_split_is_replayable():
    table = _table()
    pipeline = TablePipeline()
    derived = pipeline.derive(
        table, DataColumn("weighted", "float", False),
        lambda row: row["score"] * 2,
        operation_id="score.weight",
        configuration_digest=SHA_B,
    )
    assert derived.values("weighted") == (2.0, 6.0, 8.0, 16.0)
    first = pipeline.split(table, seed=17, fractions=(("train", 0.5), ("test", 0.5)),
                           operation_id="split", configuration_digest=SHA_B)
    second = pipeline.split(table, seed=17, fractions=(("train", 0.5), ("test", 0.5)),
                            operation_id="split", configuration_digest=SHA_B)
    assert first["train"].rows == second["train"].rows
    assert first["test"].table_digest == second["test"].table_digest


def test_scientific_statistics_centralizes_summary_effect_and_missing_policy():
    table = _table()
    stats = ScientificStatistics()
    summaries = stats.summarize(table, "score", group_by=("variant",))
    assert [(row.group, row.count, row.mean) for row in summaries] == [
        ((("variant", "control"),), 2, 2.0),
        ((("variant", "treatment"),), 2, 6.0),
    ]
    comparison = stats.compare(table, "score", "variant", baseline="control", candidate="treatment")
    assert comparison.difference == 4.0
    assert comparison.standardized_effect > 0
    nullable = DataTable("nullable", (DataColumn("score", "float"),), ((1.0,), (None,)))
    assert stats.summarize(nullable, "score", missing=MissingValuePolicy.SKIP)[0].count == 1


def test_standard_outputs_are_backend_neutral():
    table = _table()
    csv_text = StandardTableRenderer().render(table, "csv")
    markdown = StandardTableRenderer().render(table, "markdown")
    assert csv_text.splitlines()[0] == "variant,score,step"
    assert "| variant | score | step |" in markdown
    figure = FigureSpec("scores", "Scores by step", FigureKind.LINE, (
        FigureSeries("control", (FigurePoint(0, 1.0), FigurePoint(1, 3.0))),
        FigureSeries("treatment", (FigurePoint(0, 4.0), FigurePoint(1, 8.0))),
    ), y_label="score")
    svg = SvgFigureRenderer().render(figure)
    assert svg.startswith("<svg ")
    assert "Scores by step" in svg
    assert hashlib.sha256(svg.encode()).hexdigest() == hashlib.sha256(SvgFigureRenderer().render(figure).encode()).hexdigest()


def test_csv_reader_pins_source_digest_and_numeric_coercion():
    with tempfile.TemporaryDirectory(dir=".") as folder:
        source = Path(folder) / "scores.csv"
        source.write_text("variant,score\ncontrol,1.5\ntreatment,2.5\n", encoding="utf-8")
        table = CsvTableReader(coerce_numeric=True).read(str(source), table_id="csv-scores")
        assert table.values("score") == (1.5, 2.5)
        assert table.source_digest == hashlib.sha256(source.read_bytes()).hexdigest()

def test_pipeline_aggregates_and_joins_without_reimplementing_group_logic():
    table = _table()
    pipeline = TablePipeline()
    summary = pipeline.aggregate(
        table, ("variant",),
        (AggregationSpec("n", AggregationFunction.COUNT, data_type="int"),
         AggregationSpec("mean_score", AggregationFunction.MEAN, "score")),
        operation_id="summary", configuration_digest=SHA_B,
    )
    assert summary.rows == (("control", 2, 2.0), ("treatment", 2, 6.0))
    steps = DataTable("steps", (DataColumn("variant", "text"), DataColumn("label", "text")),
                      (("control", "baseline"), ("treatment", "new")))
    joined = pipeline.join(summary, steps, ("variant",), operation_id="join", configuration_digest=SHA_B)
    assert joined.column_names == ("variant", "n", "mean_score", "label")
    assert joined.rows[1][-1] == "new"


def test_split_strategies_preserve_research_units():
    table = DataTable(
        "episodes",
        (DataColumn("group", "text"), DataColumn("episode", "int"), DataColumn("score", "float")),
        (("a", 1, 1.0), ("a", 2, 2.0), ("b", 3, 3.0), ("b", 4, 4.0)),
        source_digest=SHA_A,
    )
    pipeline = TablePipeline()
    grouped = pipeline.split(table, seed=3, fractions=(("train", .5), ("test", .5)),
                             operation_id="group-split", configuration_digest=SHA_B,
                             strategy=SplitStrategy.GROUP, group_by=("group",))
    assert {row[0] for row in grouped["train"].rows}.isdisjoint({row[0] for row in grouped["test"].rows})
    temporal = pipeline.split(table, seed=3, fractions=(("train", .5), ("test", .5)),
                              operation_id="time-split", configuration_digest=SHA_B,
                              strategy=SplitStrategy.TEMPORAL, order_by=("episode",))
    assert temporal["train"].rows[-1][1] < temporal["test"].rows[0][1]



def test_inference_authority_supports_bootstrap_permutation_and_paired_units():
    table = DataTable(
        "paired",
        (DataColumn("unit", "text"), DataColumn("variant", "text"), DataColumn("score", "float")),
        (("u1", "control", 1.0), ("u1", "candidate", 2.0),
         ("u2", "control", 2.0), ("u2", "candidate", 4.0),
         ("u3", "control", 3.0), ("u3", "candidate", 5.0)),
    )
    stats = ScientificStatistics()
    paired = stats.paired_compare(table, "score", "variant", pair_column="unit",
                                   baseline="control", candidate="candidate")
    assert paired.count == 3 and paired.mean_difference == 5 / 3
    bootstrap = stats.bootstrap_mean(table, "score", replicates=100, seed=7)
    assert bootstrap.confidence95_low <= bootstrap.estimate <= bootstrap.confidence95_high
    permutation = stats.permutation_compare(table, "score", "variant",
                                             baseline="control", candidate="candidate",
                                             replicates=100, seed=7)
    assert 0.0 < permutation.p_value <= 1.0


def test_figure_semantics_support_uncertainty_boxplot_and_heatmap():
    renderer = SvgFigureRenderer()
    line = FigureSpec("ci", "Learning curve", FigureKind.LINE, (
        FigureSeries("method", (FigurePoint(0, 1.0, .8, 1.2), FigurePoint(1, 2.0, 1.7, 2.3))),
    ))
    assert "stroke=" in renderer.render(line)
    box = FigureSpec("box", "Returns", FigureKind.BOXPLOT, (
        FigureSeries("PPO", (FigurePoint(0, 1.0), FigurePoint(1, 2.0), FigurePoint(2, 4.0))),
    ))
    assert "<rect" in renderer.render(box)
    heatmap = FigureSpec("heat", "Confusion", FigureKind.HEATMAP, (), cells=(
        FigureCell("actual", "predicted", 1.0), FigureCell("actual", "other", 0.0),
    ))
    assert "rgb(" in renderer.render(heatmap)

def test_table_schema_rejects_wrong_types_and_non_nullable_nulls():
    import pytest

    with pytest.raises(TypeError):
        DataTable("bad-type", (DataColumn("score", "float", False),), (("not-number",),))
    with pytest.raises(ValueError):
        DataTable("bad-null", (DataColumn("score", "float", False),), ((None,),))

def test_study_observation_adapter_feeds_shared_statistics_and_figures():
    observations = tuple(
        StudyMetricObservation(
            StudyAssignment("study", variant, repetition, f"seed-{repetition}"),
            (("return", float(score)), ("latency", float(10 + repetition))),
        )
        for repetition, (variant, score) in enumerate(
            (("control", 1), ("control", 3), ("candidate", 4), ("candidate", 8))
        )
    )
    table = StudyObservationTableAdapter().to_table(observations)
    summaries = ScientificStatistics().summarize(table, "return", group_by=("variant_id",))
    assert {dict(row.group)["variant_id"]: row.mean for row in summaries} == {
        "control": 2.0,
        "candidate": 6.0,
    }
    figure = FigureSpec("returns", "Returns", FigureKind.BAR, (
        FigureSeries("control", (FigurePoint("control", 2.0),)),
        FigureSeries("candidate", (FigurePoint("candidate", 6.0),)),
    ), source_digests=(table.table_digest,))
    assert table.table_digest in figure.source_digests


def test_research_lifecycle_binds_baseline_identity_and_publishes_one_report():
    table = _table()
    lifecycle = ResearchLifecycle()
    lifecycle.baselines.register(BaselineSpec(
        "control", "fixed-control", SHA_B, SHA_A, SHA_B,
    ))
    context = EvaluationContext(
        "project", "experiment", "study", "treatment", EvaluationStage.TEST,
        SHA_A, SHA_B, SHA_B, "commit", SHA_B, "seed-1",
        baseline_id="control", run_id="run-1",
    )
    figure = FigureSpec(
        "scores", "Scores", FigureKind.BAR,
        (FigureSeries("treatment", (FigurePoint("treatment", 6.0),)),
        ),
        source_digests=(table.table_digest,),
    )
    result = lifecycle.evaluate(
        table, context, metric="score", group_by=("variant",),
        comparison_group="variant", baseline_value="control",
        candidate_value="treatment", figures=(figure,),
    )
    assert result.context.locked
    assert result.comparison is not None
    assert result.comparison.difference == 4.0
    assert result.report.tables == (table,)
    assert result.report.figures == (figure,)


def test_research_lifecycle_renders_one_identity_bound_package():
    table = _table()
    context = EvaluationContext(
        "project", "experiment", "study", "treatment", EvaluationStage.DEVELOPMENT,
        SHA_A, SHA_B, SHA_B, "commit", SHA_B, "seed-1",
    )
    figure = FigureSpec(
        "scores", "Scores", FigureKind.BAR,
        (FigureSeries("treatment", (FigurePoint("treatment", 6.0),)),),
        source_digests=(table.table_digest,),
    )
    evaluation = ResearchLifecycle().evaluate(
        table, context, metric="score", figures=(figure,),
    )
    rendered = ResearchLifecycle().render(
        evaluation,
        table_renderer=StandardTableRenderer(),
        figure_renderer=SvgFigureRenderer(),
        output_format=FigureOutputFormat.SVG,
    )
    assert rendered.evaluation_digest == evaluation.evaluation_digest
    assert rendered.table_format == "markdown"
    assert "| variant | score | step |" in rendered.table_text
    assert rendered.figures[0][0] == "scores"
    assert rendered.figures[0][1].startswith("<svg ")
    assert rendered.figure_format is FigureOutputFormat.SVG
    assert len(rendered.render_digest) == 64


def test_research_lifecycle_compares_all_candidates_against_one_baseline():
    table = DataTable(
        "multi-method",
        (DataColumn("variant", "text", False), DataColumn("score", "float", False)),
        (("control", 1.0), ("candidate-a", 2.0), ("candidate-b", 4.0)),
    )
    context = EvaluationContext(
        "project", "experiment", "study", "candidate-a", EvaluationStage.VALIDATION,
        SHA_A, SHA_B, SHA_B, "commit", SHA_B, "seed-1",
    )
    evaluation = ResearchLifecycle().evaluate(
        table,
        context,
        metric="score",
        comparison_group="variant",
        baseline_value="control",
        candidate_values=("candidate-a", "candidate-b"),
    )
    assert evaluation.comparison is evaluation.comparisons[0]
    assert tuple(item.candidate for item in evaluation.comparisons) == (
        "candidate-a", "candidate-b",
    )
    assert tuple(item.difference for item in evaluation.comparisons) == (1.0, 3.0)


def test_research_lifecycle_adapts_authoritative_measurement_records_once():
    assignments = (
        StudyAssignment("study", "control", 0, "seed-1"),
        StudyAssignment("study", "candidate-a", 0, "seed-1"),
    )
    records = tuple(
        MeasurementRecord(
            "project",
            "study",
            "run-1",
            assignment.assignment_digest,
            assignment.variant_id,
            "method-provider",
            SHA_B,
            "return",
            "scalar-return",
            SHA_B,
            SHA_B,
            MeasurementValue(MeasurementValueKind.SCALAR, scalar=value),
            "step-0",
            OptionalIdentityFacet(),
            OptionalIdentityFacet(),
        )
        for assignment, value in zip(assignments, (1.0, 3.5), strict=True)
    )
    context = EvaluationContext(
        "project", "experiment", "study", "candidate-a", EvaluationStage.TEST,
        SHA_A, SHA_B, SHA_B, "commit", SHA_B, "seed-1", run_id="run-1",
    )
    evaluation = ResearchLifecycle().evaluate_measurement_records(
        records,
        context,
        measurement_id="return",
        comparison_group="variant_id",
        baseline_value="control",
        candidate_value="candidate-a",
    )
    assert evaluation.table.column_names[3:7] == (
        "variant_id", "measurement_id", "logical_time", "value",
    )
    assert evaluation.comparison is not None
    assert evaluation.comparison.difference == 2.5


def test_research_lifecycle_rejects_baseline_protocol_drift():
    lifecycle = ResearchLifecycle()
    lifecycle.baselines.register(BaselineSpec(
        "control", "fixed-control", SHA_B, SHA_A, SHA_B,
    ))
    context = EvaluationContext(
        "project", "experiment", "study", "treatment", EvaluationStage.TEST,
        SHA_A, SHA_B, "c" * 64, "commit", SHA_B, "seed-1",
        baseline_id="control",
    )
    import pytest
    with pytest.raises(ValueError, match="protocol digest"):
        lifecycle.baselines.validate(context)


def test_temporal_split_orders_numeric_time_without_string_lexicographic_drift():
    table = DataTable(
        "numeric-time",
        (DataColumn("time", "int", False), DataColumn("score", "float", False)),
        ((2, 2.0), (10, 10.0), (11, 11.0)),
    )
    splits = TablePipeline().split(
        table, seed=0, fractions=(("train", 2 / 3), ("test", 1 / 3)),
        operation_id="numeric-time", configuration_digest=SHA_B,
        strategy=SplitStrategy.TEMPORAL, order_by=("time",),
    )
    assert [row[0] for row in splits["train"].rows] == [2, 10]
    assert [row[0] for row in splits["test"].rows] == [11]


def test_figure_factory_centralizes_publication_semantics_and_style():
    table = DataTable(
        "curve-data",
        (DataColumn("step", "int", False), DataColumn("method", "text", False), DataColumn("score", "float", False)),
        ((1, "A", 1.0), (2, "A", 3.0), (1, "B", 2.0), (2, "B", 4.0)),
    )
    factory = ResearchFigureFactory(style=FigureStyle.science())
    curve = factory.curve(table, x_column="step", y_column="score", series_column="method")
    assert curve.kind is FigureKind.LINE
    assert curve.category.value == "trend"
    assert curve.style.name == "science"
    assert [point.x for point in curve.series[0].points] == [1, 2]
    benchmark = factory.benchmark(table, method_column="method", metric_column="score")
    assert benchmark.kind is FigureKind.BAR
    violin = factory.distribution(table, value_column="score", group_column="method", kind=FigureKind.VIOLIN)
    assert "fill-opacity" in SvgFigureRenderer().render(violin)
    matrix = factory.matrix(
        DataTable("matrix", (DataColumn("row", "text"), DataColumn("col", "text"), DataColumn("value", "float")),
                  (("r", "c", 1.0),)),
        row_column="row", column_column="col", value_column="value",
        kind=FigureKind.CONFUSION_MATRIX,
    )
    assert "rgb(" in SvgFigureRenderer().render(matrix)


def test_baseline_catalog_is_deterministic_and_auditable():
    lifecycle = ResearchLifecycle()
    lifecycle.baselines.register(BaselineSpec(
        "z-baseline", "impl-z", SHA_A, SHA_A, SHA_B,
        reference="Paper Z", source_uri="https://example.invalid/z",
        license="MIT", tags=("classic", "retrieval"),
    ))
    lifecycle.baselines.register(BaselineSpec(
        "a-baseline", "impl-a", SHA_B, SHA_A, SHA_B,
        reference="Paper A", source_uri="https://example.invalid/a",
        license="Apache-2.0", tags=("strong",),
    ))
    catalog = lifecycle.baselines.catalog()
    assert tuple(item.baseline_id for item in catalog) == ("a-baseline", "z-baseline")
    assert catalog[0].reference == "Paper A"
    assert catalog[0].baseline_digest != BaselineSpec(
        "a-baseline", "impl-a", SHA_B, SHA_A, SHA_B,
        reference="Paper A", source_uri="https://example.invalid/a",
        license="BSD-3-Clause", tags=("strong",),
    ).baseline_digest


def test_multiple_comparison_correction_is_shared_and_replayable():
    statistics = ScientificStatistics()
    result = statistics.adjust_p_values(
        (0.01, 0.04, 0.20), method=MultipleComparisonMethod.HOLM,
    )
    assert result.adjusted_p_values == (0.03, 0.08, 0.20)
    assert result.reject == (True, False, False)
    assert len(result.result_digest) == 64


def test_compare_many_attaches_raw_and_adjusted_p_values():
    table = DataTable(
        "multi-method-p-values",
        (DataColumn("variant", "text", False), DataColumn("score", "float", False)),
        (("control", 1.0), ("candidate-a", 2.0), ("candidate-b", 4.0)),
    )
    results = ScientificStatistics().compare_many(
        table, "score", "variant", baseline="control",
        candidates=("candidate-a", "candidate-b"),
    )
    assert all(result.p_value is not None for result in results)
    assert all(result.adjusted_p_value is not None for result in results)
    assert all(result.adjusted_p_value >= result.p_value for result in results)


def test_classification_curve_uses_numeric_axis_and_reference_diagonal():
    table = DataTable(
        "roc-data",
        (DataColumn("fpr", "float", False), DataColumn("tpr", "float", False)),
        ((0.0, 0.0), (0.25, 0.60), (1.0, 1.0)),
    )
    figure = ResearchFigureFactory().classification_curve(
        table, x_column="fpr", y_column="tpr", kind=FigureKind.ROC,
    )
    rendered = SvgFigureRenderer().render(figure)
    assert "stroke-dasharray=\"6,5\"" in rendered
    assert "stroke=\"#D9E1EA\"" in rendered

def test_publication_renderer_defaults_to_pdf_and_can_emit_svg():
    figure = FigureSpec(
        "publication", "Publication", FigureKind.LINE,
        (FigureSeries("method", (FigurePoint(0, 1.0), FigurePoint(1, 2.0))),),
        x_label="step", y_label="score",
    )
    renderer = PublicationFigureRenderer()
    pdf = renderer.render(figure)
    assert pdf.startswith("data:application/pdf;base64,")
    assert base64.b64decode(pdf.split(",", 1)[1]).startswith(b"%PDF-1.4")
    svg = renderer.render(figure, output_format=FigureOutputFormat.SVG)
    assert svg.startswith("<svg ")


def test_pdf_renderer_supports_matrix_and_is_deterministic():
    figure = FigureSpec(
        "matrix", "Confusion", FigureKind.CONFUSION_MATRIX, (),
        cells=(FigureCell("actual", "predicted", 1.0), FigureCell("actual", "other", 0.0)),
    )
    renderer = PdfFigureRenderer()
    first = renderer.render(figure)
    second = renderer.render(figure)
    assert first == second
    assert base64.b64decode(first.split(",", 1)[1]).count(b"/Type /Page ") == 1

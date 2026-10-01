from __future__ import annotations

import hashlib
import json

from noetrium_platform.composition.research_execution_content import (
    compose_research_execution_content,
)
from noetrium_platform.foundation.governance.api import ScopeIdentity, ScopeKind
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.lifecycle.api import (
    BenchmarkTaskSet,
    ExperimentTrialProtocolIdentity,
    MeasurementDefinition,
    Study,
    StudyParticipant,
    TaskDefinition,
    TrialBudget,
)
from research.benchmarks.contracts import RepositoryBenchmarkTaskProjectionSpec
import research.reproductions.benchmark_input_materializer as materializer


def _study(tmp_path, *, document: dict[str, object]):
    content = compose_research_execution_content(tmp_path / "content")
    payload = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    reference = content.publish(
        reference_id=f"fixture:task:{digest}",
        scope=ScopeIdentity(ScopeKind.PROJECT, "fixture-project"),
        payload=payload,
        media_type="application/json",
    )
    task = TaskDefinition(
        task_id="task-1",
        revision_id="fixture-v1",
        family="fixture",
        schema_id="fixture.task.v1",
        content_digest=digest,
        content_reference=reference,
    )
    benchmark = BenchmarkTaskSet(
        benchmark_id="fixture-benchmark",
        revision_id="fixture-v1",
        source_digest=canonical_digest({"source": "fixture"}),
        task_schema_id="fixture.task.v1",
        tasks=(task,),
    )
    study = Study(
        project_id="fixture-project",
        study_id="fixture-study",
        benchmark=benchmark,
        method=StudyParticipant(
            role="agent",
            kind="agent",
            implementation="fixture-method",
            treatment="fixture-treatment",
        ),
        models={},
        measurements=(
            MeasurementDefinition.scalar(
                "score",
                schema_id="measurement.scalar.v1",
                semantic_kind="fixture_score",
                scale="continuous",
            ),
        ),
        trial=ExperimentTrialProtocolIdentity(
            "fixture-trial",
            canonical_digest({"trial": "fixture"}),
        ),
        repetitions=1,
        seeds=("seed",),
        limits=TrialBudget("fixture-budget", max_steps=7, max_seconds=13.0),
    ).build()
    return study, content


def test_repository_projection_materializes_public_task_payload(monkeypatch, tmp_path) -> None:
    study, content = _study(
        tmp_path,
        document={
            "prompt": {"text": "Solve the task"},
            "public": {"difficulty": 3},
            "gold": {"answer": "SECRET"},
        },
    )
    spec = RepositoryBenchmarkTaskProjectionSpec(
        benchmark_id="fixture-benchmark",
        task_schema_id="fixture.task.v1",
        objective_path="prompt.text",
        payload_fields=(("difficulty", "public.difficulty"),),
    )
    monkeypatch.setattr(
        materializer,
        "repository_benchmark_task_projection_specs",
        lambda: (spec,),
    )

    projection = materializer.materialize_repository_trial_task_projection(
        study,
        content=content,
    )
    assert len(projection.tasks) == 1
    task = projection.tasks[0]
    assert task.objective == "Solve the task"
    assert task.payload == {"difficulty": 3}
    assert "gold" not in task.payload
    assert task.max_steps == 7
    assert task.max_seconds == 13.0


def test_repository_projection_fails_closed_on_missing_declared_path(
    monkeypatch, tmp_path
) -> None:
    study, content = _study(tmp_path, document={"prompt": {"text": "Solve"}})
    spec = RepositoryBenchmarkTaskProjectionSpec(
        benchmark_id="fixture-benchmark",
        task_schema_id="fixture.task.v1",
        objective_path="missing.text",
    )
    monkeypatch.setattr(
        materializer,
        "repository_benchmark_task_projection_specs",
        lambda: (spec,),
    )

    try:
        materializer.materialize_repository_trial_task_projection(
            study,
            content=content,
        )
    except KeyError as exc:
        assert "missing.text" in str(exc)
    else:
        raise AssertionError("missing benchmark task path must fail closed")

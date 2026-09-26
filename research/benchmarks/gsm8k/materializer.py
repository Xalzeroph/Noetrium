from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.composition.research_execution_content import (
    ResearchExecutionContentAuthorities,
)
from noetrium_platform.foundation.kernel.kernel import canonical_bytes, canonical_digest
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.research.experimentation.lifecycle.api import (
    BenchmarkSourceResolution,
    ResearchStudyDefinition,
)
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    BenchmarkResolutionRegistration,
)
from research.benchmarks.contracts import RepositoryBenchmarkTaskProjectionSpec

from .verifier import GSM8KTaskVerifier

from .cut import (
    GSM8K_ARCHIVED_COMMIT,
    GSM8K_BENCHMARK_ID,
    GSM8K_FINAL_ANSWER_MARKER,
    GSM8K_SPLIT_COUNTS,
    GSM8K_TASK_SCHEMA_ID,
    GSM8KTaskRecord,
    build_gsm8k_source,
    build_gsm8k_task_set,
)

GSM8K_ARCHIVED_TEST_GIT_BLOB_SHA1 = "e4c2ff4942b9a78bd74f04141224c11e28d12dc9"
GSM8K_ARCHIVED_TEST_SHA256 = (
    "3730d312f6e3440559ace48831e51066acaca737f6eabec99bccb9e4b3c39d14"
)


@dataclass(frozen=True, slots=True)
class GSM8KMaterializedTask:
    record: GSM8KTaskRecord
    question: str
    answer: str
    final_answer: str

GSM8K_REPOSITORY_TEST_INPUT = "benchmark.gsm8k.test_jsonl"


@dataclass(frozen=True, slots=True)
class GSM8KMaterialization:
    split_id: str
    git_blob_sha1: str
    file_sha256: str
    tasks: tuple[GSM8KMaterializedTask, ...]
    cut: object

    def task(self, task_id: str) -> GSM8KMaterializedTask:
        for row in self.tasks:
            if row.record.task_id == task_id:
                return row
        raise KeyError(task_id)


def _git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _final_answer(answer: str, index: int) -> str:
    marker_index = answer.rfind(GSM8K_FINAL_ANSWER_MARKER)
    if marker_index < 0:
        raise ValueError(f"GSM8K row {index} has no final-answer marker")
    value = answer[marker_index + len(GSM8K_FINAL_ANSWER_MARKER):].strip()
    if not value:
        raise ValueError(f"GSM8K row {index} has empty final answer")
    return value


def _task_content_document(
    *,
    git_blob_sha1: str,
    file_sha256: str,
    split_id: str,
    index: int,
    question: str,
    answer: str,
) -> dict[str, object]:
    return {
        "source_commit": GSM8K_ARCHIVED_COMMIT,
        "source_git_blob_sha1": git_blob_sha1,
        "source_file_sha256": file_sha256,
        "split_id": split_id,
        "index": index,
        "question": question,
        "answer": answer,
    }


def register_gsm8k_materialization(
    materialization: GSM8KMaterialization,
) -> BenchmarkResolutionRegistration:
    """Freeze one verified GSM8K materialization into Benchmark authority."""

    if type(materialization) is not GSM8KMaterialization:
        raise TypeError(
            "GSM8K benchmark registration requires GSM8KMaterialization"
        )
    resolution = BenchmarkSourceResolution(
        source=build_gsm8k_source(
            dataset_content_sha256=materialization.file_sha256,
        ),
        task_set=materialization.cut,
    )
    proof_digest = canonical_digest(
        {
            "schema": "gsm8k.materialized.benchmark-authority-proof.v1",
            "archived_commit": GSM8K_ARCHIVED_COMMIT,
            "git_blob_sha1": materialization.git_blob_sha1,
            "file_sha256": materialization.file_sha256,
            "split_id": materialization.split_id,
            "resolution_digest": resolution.resolution_digest,
        }
    )
    return BenchmarkResolutionRegistration(
        resolution,
        proof_digest,
    )


def materialize_gsm8k_jsonl_bytes(
    data: bytes,
    *,
    split_id: str,
    expected_git_blob_sha1: str | None = None,
    expected_file_sha256: str | None = None,
    require_full_split_cardinality: bool = True,
) -> GSM8KMaterialization:
    """Bind exact JSONL bytes to immutable GSM8K task and runtime authorities."""

    if type(data) is not bytes:
        raise TypeError("GSM8K materializer data must be bytes")
    if split_id not in GSM8K_SPLIT_COUNTS:
        raise ValueError(f"unsupported GSM8K split: {split_id!r}")
    git_blob_sha1 = _git_blob_sha1(data)
    file_sha256 = hashlib.sha256(data).hexdigest()
    if expected_git_blob_sha1 is not None and git_blob_sha1 != expected_git_blob_sha1:
        raise ValueError("GSM8K Git blob identity mismatch")
    if expected_file_sha256 is not None and file_sha256 != expected_file_sha256:
        raise ValueError("GSM8K raw-file SHA256 mismatch")

    tasks: list[GSM8KMaterializedTask] = []
    for index, raw_line in enumerate(data.splitlines()):
        if not raw_line.strip():
            raise ValueError(f"GSM8K JSONL row {index} is blank")
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"GSM8K JSONL row {index} is malformed") from exc
        if not isinstance(row, dict):
            raise TypeError(f"GSM8K JSONL row {index} must be an object")
        question = row.get("question")
        answer = row.get("answer")
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"GSM8K row {index} has no question")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError(f"GSM8K row {index} has no answer")
        final_answer = _final_answer(answer, index)
        record = GSM8KTaskRecord(
            split_id=split_id,
            index=index,
            question_digest=hashlib.sha256(question.encode("utf-8")).hexdigest(),
            answer_digest=hashlib.sha256(answer.encode("utf-8")).hexdigest(),
            content_digest=canonical_digest(
                _task_content_document(
                    git_blob_sha1=git_blob_sha1,
                    file_sha256=file_sha256,
                    split_id=split_id,
                    index=index,
                    question=question,
                    answer=answer,
                )
            ),
        )
        tasks.append(GSM8KMaterializedTask(record, question, answer, final_answer))

    expected_count = GSM8K_SPLIT_COUNTS[split_id]
    if require_full_split_cardinality and len(tasks) != expected_count:
        raise ValueError(
            f"GSM8K {split_id} requires {expected_count} tasks, got {len(tasks)}"
        )
    records = tuple(task.record for task in tasks)
    cut = build_gsm8k_task_set(
        records,
        dataset_content_sha256=file_sha256,
        require_full_split_cardinality=require_full_split_cardinality,
    )
    return GSM8KMaterialization(
        split_id=split_id,
        git_blob_sha1=git_blob_sha1,
        file_sha256=file_sha256,
        tasks=tuple(tasks),
        cut=cut,
    )



def materialize_gsm8k_jsonl(
    path: str | Path,
    *,
    split_id: str,
    expected_git_blob_sha1: str | None = None,
    expected_file_sha256: str | None = None,
    require_full_split_cardinality: bool = True,
) -> GSM8KMaterialization:
    """Path adapter over the content-authoritative bytes materializer."""

    return materialize_gsm8k_jsonl_bytes(
        Path(path).read_bytes(),
        split_id=split_id,
        expected_git_blob_sha1=expected_git_blob_sha1,
        expected_file_sha256=expected_file_sha256,
        require_full_split_cardinality=require_full_split_cardinality,
    )

def materialize_archived_gsm8k_test(path: str | Path) -> GSM8KMaterialization:
    return materialize_gsm8k_jsonl(
        path,
        split_id="test",
        expected_git_blob_sha1=GSM8K_ARCHIVED_TEST_GIT_BLOB_SHA1,
        expected_file_sha256=GSM8K_ARCHIVED_TEST_SHA256,
    )


def repository_task_projection_spec() -> RepositoryBenchmarkTaskProjectionSpec:
    return RepositoryBenchmarkTaskProjectionSpec(
        benchmark_id=GSM8K_BENCHMARK_ID,
        task_schema_id=GSM8K_TASK_SCHEMA_ID,
        objective_path="question",
        payload_fields=(
            ("question", "question"),
            ("split_id", "split_id"),
            ("index", "index"),
        ),
    )


def materialize_repository_task_verifier(
    study: ResearchStudyDefinition,
    *,
    content: ResearchExecutionContentAuthorities,
) -> GSM8KTaskVerifier:
    """Bind the benchmark-owned artifact-only verifier to one exact Study."""

    return GSM8KTaskVerifier.from_study(study, content=content)


def materialize_repository_benchmark_authority(
    authority_inputs: tuple[tuple[str, str], ...],
    *,
    content: ResearchExecutionContentAuthorities,
) -> tuple[BenchmarkResolutionRegistration, ...]:
    """Materialize the exact cut and publish its source/task bytes once."""

    if type(content) is not ResearchExecutionContentAuthorities:
        raise TypeError(
            "GSM8K repository materialization requires "
            "ResearchExecutionContentAuthorities"
        )
    path = dict(authority_inputs).get(GSM8K_REPOSITORY_TEST_INPUT)
    if path is None:
        return ()

    source_path = Path(path).resolve(strict=True)
    source_bytes = source_path.read_bytes()
    materialized = materialize_gsm8k_jsonl_bytes(
        source_bytes,
        split_id="test",
        expected_git_blob_sha1=GSM8K_ARCHIVED_TEST_GIT_BLOB_SHA1,
        expected_file_sha256=GSM8K_ARCHIVED_TEST_SHA256,
    )
    scope = ScopeIdentity(ScopeKind.PLATFORM, "benchmark:gsm8k")
    source_reference = content.publish(
        reference_id=f"gsm8k:source:{materialized.file_sha256}",
        scope=scope,
        payload=source_bytes,
        media_type="application/x-ndjson",
        producer_component_id="research.benchmarks.gsm8k",
    )
    content_references = {}
    for task in materialized.tasks:
        document = _task_content_document(
            git_blob_sha1=materialized.git_blob_sha1,
            file_sha256=materialized.file_sha256,
            split_id=task.record.split_id,
            index=task.record.index,
            question=task.question,
            answer=task.answer,
        )
        payload = canonical_bytes(document)
        if hashlib.sha256(payload).hexdigest() != task.record.content_digest:
            raise RuntimeError("GSM8K canonical task content digest drifted")
        content_references[task.record.task_id] = content.publish(
            reference_id=f"gsm8k:task:{task.record.content_digest}",
            scope=scope,
            payload=payload,
            media_type="application/json",
            producer_component_id="research.benchmarks.gsm8k",
        )

    cut = build_gsm8k_task_set(
        tuple(task.record for task in materialized.tasks),
        dataset_content_sha256=materialized.file_sha256,
        source_reference=source_reference,
        content_references=content_references,
    )
    bound = GSM8KMaterialization(
        split_id=materialized.split_id,
        git_blob_sha1=materialized.git_blob_sha1,
        file_sha256=materialized.file_sha256,
        tasks=materialized.tasks,
        cut=cut,
    )
    return (register_gsm8k_materialization(bound),)


__all__ = [
    "GSM8K_ARCHIVED_TEST_GIT_BLOB_SHA1",
    "GSM8K_ARCHIVED_TEST_SHA256",
    "GSM8K_REPOSITORY_TEST_INPUT",
    "GSM8KMaterialization",
    "GSM8KMaterializedTask",
    "materialize_archived_gsm8k_test",
    "materialize_gsm8k_jsonl",
    "materialize_gsm8k_jsonl_bytes",
    "materialize_repository_benchmark_authority",
    "materialize_repository_task_verifier",
    "register_gsm8k_materialization",
    "repository_task_projection_spec",
]

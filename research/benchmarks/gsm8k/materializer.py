from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import canonical_digest

from .cut import (
    GSM8K_ARCHIVED_COMMIT,
    GSM8K_FINAL_ANSWER_MARKER,
    GSM8K_SPLIT_COUNTS,
    GSM8KTaskRecord,
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


def materialize_gsm8k_jsonl(
    path: str | Path,
    *,
    split_id: str,
    expected_git_blob_sha1: str | None = None,
    expected_file_sha256: str | None = None,
    require_full_split_cardinality: bool = True,
) -> GSM8KMaterialization:
    """Bind exact JSONL bytes to immutable GSM8K task and runtime authorities."""

    if split_id not in GSM8K_SPLIT_COUNTS:
        raise ValueError(f"unsupported GSM8K split: {split_id!r}")
    data = Path(path).read_bytes()
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
                {
                    "source_commit": GSM8K_ARCHIVED_COMMIT,
                    "source_git_blob_sha1": git_blob_sha1,
                    "source_file_sha256": file_sha256,
                    "split_id": split_id,
                    "index": index,
                    "question": question,
                    "answer": answer,
                }
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


def materialize_archived_gsm8k_test(path: str | Path) -> GSM8KMaterialization:
    return materialize_gsm8k_jsonl(
        path,
        split_id="test",
        expected_git_blob_sha1=GSM8K_ARCHIVED_TEST_GIT_BLOB_SHA1,
        expected_file_sha256=GSM8K_ARCHIVED_TEST_SHA256,
    )


__all__ = [
    "GSM8K_ARCHIVED_TEST_GIT_BLOB_SHA1",
    "GSM8K_ARCHIVED_TEST_SHA256",
    "GSM8KMaterialization",
    "GSM8KMaterializedTask",
    "materialize_archived_gsm8k_test",
    "materialize_gsm8k_jsonl",
]

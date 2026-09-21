"""Pinned GSM8K benchmark cut for reasoning-method reproductions."""

from .materializer import (
    GSM8K_ARCHIVED_TEST_GIT_BLOB_SHA1,
    GSM8K_ARCHIVED_TEST_SHA256,
    GSM8KMaterialization,
    GSM8KMaterializedTask,
    materialize_archived_gsm8k_test,
    materialize_gsm8k_jsonl,
)
from .verifier import (
    extract_gsm8k_completion_answer,
    normalize_gsm8k_numeric_answer,
    verify_gsm8k_completion,
)

from .cut import (
    GSM8K_ARCHIVED_COMMIT,
    GSM8K_BENCHMARK_ID,
    GSM8K_FINAL_ANSWER_MARKER,
    GSM8K_RELEASE_COMMIT,
    GSM8K_REPOSITORY,
    GSM8K_SPLIT_COUNTS,
    GSM8K_TASK_SCHEMA_ID,
    GSM8KTaskRecord,
    build_gsm8k_source,
    build_gsm8k_task_set,
    gsm8k_revision,
)

__all__ = [
    "materialize_gsm8k_jsonl",
    "materialize_archived_gsm8k_test",
    "verify_gsm8k_completion",
    "normalize_gsm8k_numeric_answer",
    "extract_gsm8k_completion_answer",
    "GSM8KMaterializedTask",
    "GSM8KMaterialization",
    "GSM8K_ARCHIVED_TEST_SHA256",
    "GSM8K_ARCHIVED_TEST_GIT_BLOB_SHA1",
    "GSM8K_ARCHIVED_COMMIT",
    "GSM8K_BENCHMARK_ID",
    "GSM8K_FINAL_ANSWER_MARKER",
    "GSM8K_RELEASE_COMMIT",
    "GSM8K_REPOSITORY",
    "GSM8K_SPLIT_COUNTS",
    "GSM8K_TASK_SCHEMA_ID",
    "GSM8KTaskRecord",
    "build_gsm8k_source",
    "build_gsm8k_task_set",
    "gsm8k_revision",
]

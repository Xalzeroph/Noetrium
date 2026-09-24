from __future__ import annotations

import json

from research.benchmarks.gsm8k import (
    materialize_gsm8k_jsonl,
    register_gsm8k_materialization,
)


def test_gsm8k_raw_bytes_materialize_into_registered_exact_cut(tmp_path) -> None:
    path = tmp_path / "test.jsonl"
    path.write_text(
        json.dumps(
            {
                "question": "If one plus one equals what?",
                "answer": "Simple arithmetic. #### 2",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    materialized = materialize_gsm8k_jsonl(
        path,
        split_id="test",
        require_full_split_cardinality=False,
    )
    registration = register_gsm8k_materialization(materialized)

    assert materialized.split_id == "test"
    assert len(materialized.tasks) == 1
    assert registration.benchmark_id == "gsm8k"
    assert registration.resolution.task_set == materialized.cut
    assert registration.resolution.source.content_digest == materialized.file_sha256
    assert len(registration.authority_proof_digest) == 64
    assert len(registration.registration_digest) == 64

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from time import monotonic, sleep

from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope
from noetrium_platform.capabilities.model.request.runtime import SQLiteModelRequestLedger
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    ImmutableModelIdentity,
    canonical_digest,
)
from noetrium_platform.substrate.api import ArtifactBlobRef


_MODEL = ImmutableModelIdentity(
    "reasoner",
    "model",
    "a" * 64,
    "vllm",
    "1",
    "bf16",
    None,
    8192,
    "b" * 64,
)


def _envelope(index: int) -> ModelRequestEnvelope:
    return ModelRequestEnvelope(
        schema_version="model-request.v1",
        request_id=f"request-{index}",
        context=ExecutionContext(
            f"run-{index}",
            f"trace-{index}",
            f"span-{index}",
            study_id=f"paper-{index % 4}",
        ),
        role="reasoner",
        model=_MODEL,
        prompt_generation_id="generation",
        prompt_id="prompt",
        prompt_digest="c" * 64,
        request_body=ArtifactBlobRef(
            canonical_digest({"index": index}),
            10,
            "application/json",
        ),
    )


def test_concurrent_model_requests_share_one_full_commit(tmp_path: Path) -> None:
    ledger = SQLiteModelRequestLedger(tmp_path / "requests.sqlite3")
    original_commit_batch = ledger._commit_batch
    first_commit_entered = Event()
    release_first_commit = Event()
    committed_batches: list[tuple[str, ...]] = []

    def controlled_commit(batch):
        committed_batches.append(
            tuple(row.envelope.request_id for row in batch)
        )
        if len(committed_batches) == 1:
            first_commit_entered.set()
            assert release_first_commit.wait(timeout=5.0)
        return original_commit_batch(batch)

    ledger._commit_batch = controlled_commit  # type: ignore[method-assign]

    with ThreadPoolExecutor(max_workers=9) as executor:
        first = executor.submit(ledger.append, _envelope(0))
        assert first_commit_entered.wait(timeout=5.0)

        rest = [
            executor.submit(ledger.append, _envelope(index))
            for index in range(1, 9)
        ]
        deadline = monotonic() + 5.0
        while True:
            with ledger._batch_condition:
                pending_count = len(ledger._pending_appends)
            if pending_count == 8:
                break
            if monotonic() >= deadline:
                raise AssertionError(
                    f"concurrent requests did not queue: pending={pending_count}"
                )
            sleep(0.001)

        release_first_commit.set()
        first.result(timeout=5.0)
        for future in rest:
            future.result(timeout=5.0)

    assert tuple(map(len, committed_batches)) == (1, 8)
    assert ledger.group_commit_count == 2
    assert ledger.max_observed_group_commit_size == 8
    for index in range(9):
        assert ledger.get(f"request-{index}") == _envelope(index)
    ledger.close()


def test_serial_model_request_does_not_wait_for_group_commit_window(tmp_path: Path) -> None:
    ledger = SQLiteModelRequestLedger(tmp_path / "serial.sqlite3")
    with ledger._batch_condition:
        assert ledger._coalesce_seconds_locked() == 0.0
    ledger.append(_envelope(0))
    with ledger._batch_condition:
        assert ledger._coalesce_seconds_locked() == 0.0
    assert ledger.group_commit_count == 1
    assert ledger.max_observed_group_commit_size == 1
    ledger.close()

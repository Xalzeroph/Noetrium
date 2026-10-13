import json
from pathlib import Path

import pytest

from noetrium_platform.capabilities.model.serving.api import RecoveryPlan, RecoveryStep
from noetrium_platform.capabilities.model.serving.api.recovery_state import new_recovery_attempt
from noetrium_platform.capabilities.model.serving.providers.recovery_storage import (
    FileDurableRecoveryStore,
    RecoveryStateIntegrityError,
)
from noetrium_platform.capabilities.model.serving.providers.recovery_storage_codec import _SCHEMA
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity
from noetrium_platform.foundation.kernel.kernel.durability import (
    decode_checksummed_document,
    encode_checksummed_document,
)


def _plan() -> RecoveryPlan:
    identity = ImmutableModelIdentity(
        "model", "repo/model", "rev", "engine", "1", "bfloat16", None, 4096
    )
    return RecoveryPlan(
        "run", identity, "d" * 64, (RecoveryStep.VERIFY_ARTIFACTS,)
    )


def _store(root: Path) -> FileDurableRecoveryStore:
    return FileDurableRecoveryStore(
        root / "recovery.json", guard_path=root / "recovery.guard.lock"
    )


def _published(tmp_path: Path):
    store = _store(tmp_path)
    attempt = new_recovery_attempt("attempt", _plan(), now=1.5)
    store.create(attempt)
    path = tmp_path / "recovery.json"
    return store, attempt, path


def _rewrite_payload(path: Path, mutate) -> None:
    document = decode_checksummed_document(path.read_bytes(), expected_schema=_SCHEMA)
    payload = dict(document.payload)
    mutate(payload)
    path.write_bytes(encode_checksummed_document(_SCHEMA, payload))


def test_recovery_store_round_trips_checksummed_typed_state(tmp_path: Path) -> None:
    store, attempt, path = _published(tmp_path)

    assert store.load() == attempt
    document = decode_checksummed_document(path.read_bytes(), expected_schema=_SCHEMA)
    assert document.payload["attempt_id"] == "attempt"


def test_recovery_store_rejects_outer_checksum_tampering(tmp_path: Path) -> None:
    store, _attempt, path = _published(tmp_path)
    raw = bytearray(path.read_bytes())
    raw[-2] = ord("0") if raw[-2] != ord("0") else ord("1")
    path.write_bytes(bytes(raw))

    with pytest.raises(RecoveryStateIntegrityError):
        store.load()


def test_recovery_store_rejects_extra_field_with_valid_checksum(tmp_path: Path) -> None:
    store, _attempt, path = _published(tmp_path)
    _rewrite_payload(path, lambda payload: payload.__setitem__("unexpected", 1))

    with pytest.raises(RecoveryStateIntegrityError):
        store.load()


def test_recovery_store_rejects_string_float_with_valid_checksum(tmp_path: Path) -> None:
    store, _attempt, path = _published(tmp_path)
    _rewrite_payload(path, lambda payload: payload.__setitem__("updated_at", "1.5"))

    with pytest.raises(RecoveryStateIntegrityError):
        store.load()


def test_recovery_store_rejects_invalid_state_semantics(tmp_path: Path) -> None:
    store, _attempt, path = _published(tmp_path)
    _rewrite_payload(path, lambda payload: payload.__setitem__("evidence_refs", ["impossible"]))

    with pytest.raises(RecoveryStateIntegrityError):
        store.load()


def test_recovery_store_rejects_legacy_unchecksummed_json(tmp_path: Path) -> None:
    store, attempt, path = _published(tmp_path)
    path.write_text(json.dumps({"attempt_id": attempt.attempt_id}), encoding="utf-8")

    with pytest.raises(RecoveryStateIntegrityError):
        store.load()

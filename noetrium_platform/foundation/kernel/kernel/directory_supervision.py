"""Crash-durable child Machine supervision."""
from __future__ import annotations

from pathlib import Path

from .canonical import canonical_bytes, strict_json_loads
from .contracts import ChildMachineLink
from .durability import InterprocessFileLock, atomic_replace_bytes
from .supervision import (
    ChildMachineRecord,
    ChildMachineStatus,
    ChildMachineSupervisorPort,
    InMemoryChildMachineSupervisor,
)


def _link_document(link: ChildMachineLink) -> dict[str, object]:
    return link.as_dict()


def _record_document(record: ChildMachineRecord) -> dict[str, object]:
    return {
        "link": _link_document(record.link),
        "status": record.status.value,
        "observed_revision": record.observed_revision,
        "result_ref": record.result_ref,
        "error_ref": record.error_ref,
        "record_digest": record.record_digest,
    }


def _decode_link(value: object) -> ChildMachineLink:
    if not isinstance(value, dict) or set(value) != {
        "parent_machine_id", "child_machine_id", "child_program_digest",
        "child_snapshot_ref", "child_transition_start", "child_transition_end",
        "child_result_ref", "failure_policy", "link_digest",
    }:
        raise ValueError("child link record fields are not exact")
    link = ChildMachineLink(
        value["parent_machine_id"], value["child_machine_id"],
        value["child_program_digest"], value["child_snapshot_ref"],
        value["child_transition_start"], value["child_transition_end"],
        value["child_result_ref"], value["failure_policy"],
    )
    if link.link_digest != value["link_digest"]:
        raise ValueError("child link digest mismatch")
    return link


def _decode_record(value: object) -> ChildMachineRecord:
    if not isinstance(value, dict) or set(value) != {
        "link", "status", "observed_revision", "result_ref", "error_ref",
        "record_digest",
    }:
        raise ValueError("child record fields are not exact")
    record = ChildMachineRecord(
        _decode_link(value["link"]),
        ChildMachineStatus(value["status"]),
        value["observed_revision"],
        value["result_ref"],
        value["error_ref"],
    )
    if record.record_digest != value["record_digest"]:
        raise ValueError("child record digest mismatch")
    return record


class DirectoryChildMachineSupervisor(
    InMemoryChildMachineSupervisor, ChildMachineSupervisorPort
):
    """Canonical record ledger for parent/child lifecycle observations."""

    durability = "crash_durable"

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "children.json"
        self.lock_path = self.root / "children.lock"
        if self.path.exists():
            self._reload()

    def _reload(self) -> None:
        try:
            raw = self.path.read_bytes()
            value = strict_json_loads(raw)
            if canonical_bytes(value) != raw or not isinstance(value, list):
                raise ValueError("child supervisor record is not canonical")
            records = [_decode_record(item) for item in value]
        except (OSError, TypeError, ValueError) as exc:
            raise ValueError("child supervisor record is corrupt") from exc
        with self._lock:
            self._records = {item.link.child_machine_id: item for item in records}

    def _save(self) -> None:
        with self._lock:
            value = [_record_document(self._records[key]) for key in sorted(self._records)]
        atomic_replace_bytes(self.path, canonical_bytes(value))

    def register(self, link: ChildMachineLink) -> ChildMachineRecord:
        with InterprocessFileLock(self.lock_path):
            self._reload() if self.path.exists() else None
            record = super().register(link)
            self._save()
            return record

    def observe(self, record: ChildMachineRecord) -> ChildMachineRecord:
        with InterprocessFileLock(self.lock_path):
            self._reload() if self.path.exists() else None
            updated = super().observe(record)
            self._save()
            return updated
    def join(self, child_machine_id: str) -> ChildMachineRecord:
        with InterprocessFileLock(self.lock_path):
            self._reload() if self.path.exists() else None
            return super().join(child_machine_id)

    def cancel(self, child_machine_id: str, error_ref: str) -> ChildMachineRecord:
        if type(error_ref) is not str or not error_ref.strip():
            raise ValueError("cancel error_ref is required")
        with InterprocessFileLock(self.lock_path):
            self._reload() if self.path.exists() else None
            with self._lock:
                try:
                    current = self._records[child_machine_id]
                except KeyError as exc:
                    raise KeyError(child_machine_id) from exc
                if current.status in {
                    ChildMachineStatus.COMPLETED,
                    ChildMachineStatus.FAILED,
                    ChildMachineStatus.CANCELED,
                }:
                    return current
                updated = InMemoryChildMachineSupervisor.observe(
                    self,
                    ChildMachineRecord(
                        current.link, ChildMachineStatus.CANCELED,
                        current.observed_revision, error_ref=error_ref,
                    ),
                )
            self._save()
            return updated

    def list(self, parent_machine_id: str) -> tuple[ChildMachineRecord, ...]:
        with InterprocessFileLock(self.lock_path):
            self._reload() if self.path.exists() else None
            return super().list(parent_machine_id)


__all__ = ["DirectoryChildMachineSupervisor"]

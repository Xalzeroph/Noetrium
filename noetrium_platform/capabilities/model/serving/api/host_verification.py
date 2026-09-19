from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re

from .inventory import HostInventory, RuntimeInventory

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PHASE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_RUNTIME_FIELDS = frozenset({
    "kernel", "python", "node", "java", "nvidia_driver",
    "cuda_driver_api", "nvml", "sglang", "vllm",
})


def _digest(value: object) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value


def _phase(value: object, field: str = "phase") -> str:
    text = _text(value, field)
    if _PHASE_RE.fullmatch(text) is None:
        raise ValueError(f"{field} must be a stable token")
    return text


def _sha256(value: object, field: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be lowercase SHA-256")
    return value


def _integer(value: object, field: str, *, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        suffix = f" >= {minimum}" if minimum is not None else ""
        raise ValueError(f"{field} must be an integer{suffix}")
    return value


def _timestamp(value: object, field: str) -> float:
    if type(value) is not float or not math.isfinite(value) or value < 0:
        raise ValueError(f"{field} must be a finite non-negative JSON float")
    return value


def _pairs(
    value: object,
    field: str,
    *,
    minimum: int | None,
) -> tuple[tuple[str, int], ...]:
    if type(value) is not tuple:
        raise ValueError(f"{field} must be a tuple")
    rows: list[tuple[str, int]] = []
    for row in value:
        if type(row) is not tuple or len(row) != 2:
            raise ValueError(f"{field} rows must be two-item tuples")
        key = _text(row[0], f"{field} key")
        amount = _integer(row[1], f"{field} value", minimum=minimum)
        rows.append((key, amount))
    if len({key for key, _ in rows}) != len(rows):
        raise ValueError(f"{field} contains duplicate identities")
    return tuple(rows)


def _ports(value: object, field: str) -> tuple[int, ...]:
    if type(value) is not tuple:
        raise ValueError(f"{field} must be a tuple")
    ports = tuple(_integer(item, field, minimum=1) for item in value)
    if any(item > 65535 for item in ports):
        raise ValueError(f"{field} contains an invalid TCP/UDP port")
    if len(set(ports)) != len(ports):
        raise ValueError(f"{field} contains duplicate ports")
    return ports


def _runtime(value: object) -> RuntimeInventory:
    if type(value) is not RuntimeInventory:
        raise ValueError("runtime must be RuntimeInventory")
    _text(value.kernel, "runtime.kernel")
    _text(value.python, "runtime.python")
    for field in _RUNTIME_FIELDS - {"kernel", "python"}:
        item = getattr(value, field)
        if item is not None:
            _text(item, f"runtime.{field}")
    return value


@dataclass(frozen=True, slots=True)
class HostInventoryReceipt:
    schema_version: int
    phase: str
    host_identity_digest: str
    snapshot_digest: str
    captured_at_unix: float
    effective_available_memory_bytes: int
    gpu_free_memory_bytes: tuple[tuple[str, int], ...]
    listening_ports: tuple[int, ...]
    mount_free_bytes: tuple[tuple[str, int], ...]
    runtime: RuntimeInventory
    receipt_digest: str

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("host inventory schema_version must equal 1")
        _phase(self.phase)
        _sha256(self.host_identity_digest, "host_identity_digest")
        _sha256(self.snapshot_digest, "snapshot_digest")
        _timestamp(self.captured_at_unix, "captured_at_unix")
        _integer(
            self.effective_available_memory_bytes,
            "effective_available_memory_bytes",
            minimum=0,
        )
        _pairs(self.gpu_free_memory_bytes, "gpu_free_memory_bytes", minimum=0)
        _ports(self.listening_ports, "listening_ports")
        _pairs(self.mount_free_bytes, "mount_free_bytes", minimum=0)
        _runtime(self.runtime)
        _sha256(self.receipt_digest, "receipt_digest")
        base = {key: value for key, value in asdict(self).items() if key != "receipt_digest"}
        if _digest(base) != self.receipt_digest:
            raise ValueError("host inventory receipt digest mismatch")


@dataclass(frozen=True, slots=True)
class HostResourceDelta:
    schema_version: int
    before_phase: str
    after_phase: str
    before_snapshot_digest: str
    after_snapshot_digest: str
    host_memory_delta_bytes: int
    gpu_free_memory_delta_bytes: tuple[tuple[str, int], ...]
    ports_added: tuple[int, ...]
    ports_removed: tuple[int, ...]
    mount_free_delta_bytes: tuple[tuple[str, int], ...]
    delta_digest: str

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("host resource delta schema_version must equal 1")
        _phase(self.before_phase, "before_phase")
        _phase(self.after_phase, "after_phase")
        if self.before_phase == self.after_phase:
            raise ValueError("host resource delta phases must differ")
        _sha256(self.before_snapshot_digest, "before_snapshot_digest")
        _sha256(self.after_snapshot_digest, "after_snapshot_digest")
        _integer(self.host_memory_delta_bytes, "host_memory_delta_bytes")
        _pairs(self.gpu_free_memory_delta_bytes, "gpu_free_memory_delta_bytes", minimum=None)
        _ports(self.ports_added, "ports_added")
        _ports(self.ports_removed, "ports_removed")
        if set(self.ports_added) & set(self.ports_removed):
            raise ValueError("host resource delta cannot add and remove the same port")
        _pairs(self.mount_free_delta_bytes, "mount_free_delta_bytes", minimum=None)
        _sha256(self.delta_digest, "delta_digest")
        base = {key: value for key, value in asdict(self).items() if key != "delta_digest"}
        if _digest(base) != self.delta_digest:
            raise ValueError("host resource delta digest mismatch")


def _receipt_base(inventory: HostInventory, phase: str) -> dict[str, object]:
    _phase(phase)
    return {
        "schema_version": 1,
        "phase": phase,
        "host_identity_digest": inventory.identity_digest(),
        "snapshot_digest": inventory.snapshot_digest(),
        "captured_at_unix": inventory.captured_at_unix,
        "effective_available_memory_bytes": inventory.memory.effective_available_bytes,
        "gpu_free_memory_bytes": tuple((gpu.uuid, gpu.free_memory_bytes) for gpu in inventory.gpus),
        "listening_ports": inventory.listening_ports,
        "mount_free_bytes": tuple((mount.path, mount.free_bytes) for mount in inventory.mounts),
        "runtime": asdict(inventory.runtime),
    }


def build_host_inventory_receipt(
    expected_host_identity_digest: str,
    inventory: HostInventory,
    *,
    phase: str,
) -> HostInventoryReceipt:
    """Project the complete host inventory into an immutable receipt.

    Algorithm-Complexity: O(N)
    Algorithm-Rationale: N is the number of GPUs plus mounts and the receipt intentionally materializes one identity/free-space entry for every observed device and mount.
    """
    _sha256(expected_host_identity_digest, "expected_host_identity_digest")
    base = _receipt_base(inventory, phase)
    if base["host_identity_digest"] != expected_host_identity_digest:
        raise ValueError("live host/runtime identity differs from run launch manifest")
    return HostInventoryReceipt(
        schema_version=1,
        phase=phase,
        host_identity_digest=inventory.identity_digest(),
        snapshot_digest=inventory.snapshot_digest(),
        captured_at_unix=inventory.captured_at_unix,
        effective_available_memory_bytes=inventory.memory.effective_available_bytes,
        gpu_free_memory_bytes=tuple((gpu.uuid, gpu.free_memory_bytes) for gpu in inventory.gpus),
        listening_ports=inventory.listening_ports,
        mount_free_bytes=tuple((mount.path, mount.free_bytes) for mount in inventory.mounts),
        runtime=inventory.runtime,
        receipt_digest=_digest(base),
    )


def compare_host_inventory_receipts(
    before: HostInventoryReceipt,
    after: HostInventoryReceipt,
) -> HostResourceDelta:
    if before.host_identity_digest != after.host_identity_digest:
        raise ValueError("cannot compare host resource snapshots from different host identities")
    before_gpus = dict(before.gpu_free_memory_bytes)
    after_gpus = dict(after.gpu_free_memory_bytes)
    if set(before_gpus) != set(after_gpus):
        raise ValueError("GPU identity set changed between host resource snapshots")
    before_mounts = dict(before.mount_free_bytes)
    after_mounts = dict(after.mount_free_bytes)
    if set(before_mounts) != set(after_mounts):
        raise ValueError("mount identity set changed between host resource snapshots")

    base = {
        "schema_version": 1,
        "before_phase": before.phase,
        "after_phase": after.phase,
        "before_snapshot_digest": before.snapshot_digest,
        "after_snapshot_digest": after.snapshot_digest,
        "host_memory_delta_bytes": after.effective_available_memory_bytes - before.effective_available_memory_bytes,
        "gpu_free_memory_delta_bytes": tuple(
            (key, after_gpus[key] - before_gpus[key]) for key in sorted(before_gpus)
        ),
        "ports_added": tuple(sorted(set(after.listening_ports) - set(before.listening_ports))),
        "ports_removed": tuple(sorted(set(before.listening_ports) - set(after.listening_ports))),
        "mount_free_delta_bytes": tuple(
            (key, after_mounts[key] - before_mounts[key]) for key in sorted(before_mounts)
        ),
    }
    return HostResourceDelta(
        schema_version=1,
        before_phase=before.phase,
        after_phase=after.phase,
        before_snapshot_digest=before.snapshot_digest,
        after_snapshot_digest=after.snapshot_digest,
        host_memory_delta_bytes=base["host_memory_delta_bytes"],
        gpu_free_memory_delta_bytes=base["gpu_free_memory_delta_bytes"],
        ports_added=base["ports_added"],
        ports_removed=base["ports_removed"],
        mount_free_delta_bytes=base["mount_free_delta_bytes"],
        delta_digest=_digest(base),
    )


__all__ = [
    "HostInventoryReceipt",
    "HostResourceDelta",
    "build_host_inventory_receipt",
    "compare_host_inventory_receipts",
]

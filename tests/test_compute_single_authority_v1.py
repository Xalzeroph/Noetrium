from __future__ import annotations

from pathlib import Path

from noetrium_platform.infrastructure.resources.compute import composition, runtime
from noetrium_platform.infrastructure.resources import authority


ROOT = Path(__file__).resolve().parents[1]
COMPUTE_ROOT = ROOT / "noetrium_platform/infrastructure/resources/compute"


def test_compute_exposes_inventory_and_pure_discovery_not_scheduler_authority() -> None:
    assert runtime.__all__ == ["ComputeInventory"]
    assert composition.__all__ == ["discover_local_compute_host"]
    assert "UniversalResourceAuthority" in authority.__all__
    for retired in (
        "ComputeScheduler",
        "ComputeAuthorityStack",
        "compose_compute_authority",
        "InMemoryComputeInventory",
        "SQLiteComputeInventory",
        "InMemoryComputeScheduler",
        "SQLiteComputeScheduler",
        "compose_in_memory_compute_stack",
        "compose_in_memory_compute_scheduler",
        "bind_in_memory_compute_scheduler",
    ):
        assert not hasattr(runtime, retired)
        assert not hasattr(composition, retired)


def test_compute_product_code_contains_no_scheduler_owner_mode() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(COMPUTE_ROOT.rglob("*.py"))
    )
    for forbidden in (
        "class ComputeScheduler",
        "InMemoryComputeScheduler",
        "SQLiteComputeScheduler",
        "compose_in_memory_compute",
        "bind_in_memory_compute",
    ):
        assert forbidden not in text

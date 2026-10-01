from __future__ import annotations

from pathlib import Path

from noetrium_platform.infrastructure.resources.compute import composition, runtime


ROOT = Path(__file__).resolve().parents[1]
COMPUTE_ROOT = ROOT / "noetrium_platform/infrastructure/resources/compute"


def test_compute_exposes_one_durable_inventory_and_scheduler_authority() -> None:
    assert "ComputeInventory" in runtime.__all__
    assert "ComputeScheduler" in runtime.__all__
    assert "ComputeAuthorityStack" in composition.__all__
    assert "compose_compute_authority" in composition.__all__

    for retired in (
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


def test_compute_product_code_contains_no_second_owner_mode() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(COMPUTE_ROOT.rglob("*.py"))
    )
    for forbidden in (
        "InMemoryComputeInventory",
        "SQLiteComputeInventory",
        "InMemoryComputeScheduler",
        "SQLiteComputeScheduler",
        "compose_in_memory_compute",
        "bind_in_memory_compute",
    ):
        assert forbidden not in text

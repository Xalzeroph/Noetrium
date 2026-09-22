from __future__ import annotations

from research.runtime.phase_pressure import discover


def test_pressure_discovery_accepts_sequence_and_cycle_programs() -> None:
    packages = {name for name, _ in discover()}
    assert "adaptagent_acl2025" in packages
    assert "agemem_acl2026" in packages
    assert "astranav_memory_cvpr2026" in packages
    assert "lmee_cvpr2026" in packages
    assert "dejavu_cvpr2026" in packages


def test_pressure_discovery_routes_capability_programs_to_other_lanes() -> None:
    packages = {name for name, _ in discover()}
    assert "react_alfworld" not in packages
    assert "voyager_minecraft" not in packages
    assert "swe_agent_swebench" not in packages

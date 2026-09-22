from __future__ import annotations

from research.runtime.phase_pressure import _git_sha, discover


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



def test_pressure_source_sha_is_frozen_from_git(monkeypatch) -> None:
    monkeypatch.setattr(
        "research.runtime.phase_pressure.subprocess.check_output",
        lambda *args, **kwargs: "a" * 40 + "\n",
    )
    assert _git_sha() == "a" * 40

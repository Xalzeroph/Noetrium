from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from scripts.provider_conformance import REQUIRED, load_conformance_catalog


def test_provider_conformance_catalog_covers_required_provider_classes():
    suites = load_conformance_catalog()
    assert set(suites) == REQUIRED
    assert all(suites[class_id] for class_id in REQUIRED)


def test_provider_conformance_paths_are_top_level_classified_tests():
    root = Path(__file__).resolve().parents[1]
    suites = load_conformance_catalog()
    for relative in {path for rows in suites.values() for path in rows}:
        assert (root / relative).is_file()
        completed = subprocess.run(
            [sys.executable, "scripts/test_system.py", "explain", relative],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr

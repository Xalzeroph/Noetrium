import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_layer_facades_are_collision_free_and_contract_only() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "audit_layer_facade_contracts.py")],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    document = json.loads(result.stdout)
    assert document["violation_count"] == 0, document["violations"]
    assert result.returncode == 0


def test_generated_layer_facades_are_canonical() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_layer_facades.py"), "--check"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

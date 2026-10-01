from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from noetrium_platform.capabilities.model.serving.api import ModelAdmissionTimeout
from noetrium_platform.capabilities.model.serving.runtime import (
    InterprocessModelAdmissionRegistry,
)


_GENERATION = "a" * 64


def test_interprocess_model_admission_enforces_one_host_wide_ceiling(tmp_path: Path) -> None:
    root = tmp_path / "model-admission"
    script = r'''
import sys, time
from pathlib import Path
from noetrium_platform.capabilities.model.serving.runtime import InterprocessModelAdmissionRegistry
root = Path(sys.argv[1])
registry = InterprocessModelAdmissionRegistry(root)
controller = registry.controller_for(deployment_id="model", deployment_generation="a"*64, qualified_capacity=1)
lease = controller.acquire(timeout_seconds=1.0, owner_id="child")
print("READY", flush=True)
time.sleep(0.6)
lease.release()
registry.close()
'''
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(root)],
        cwd=Path.cwd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "READY"
        registry = InterprocessModelAdmissionRegistry(root)
        controller = registry.controller_for(
            deployment_id="model",
            deployment_generation=_GENERATION,
            qualified_capacity=1,
        )
        with pytest.raises(ModelAdmissionTimeout):
            controller.acquire(timeout_seconds=0.1, owner_id="parent")
        assert child.wait(timeout=3.0) == 0
        with controller.acquire(timeout_seconds=0.5, owner_id="parent"):
            pass
        registry.close()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=3.0)


def test_interprocess_model_admission_rejects_capacity_drift(tmp_path: Path) -> None:
    root = tmp_path / "model-admission"
    first = InterprocessModelAdmissionRegistry(root)
    first.controller_for(
        deployment_id="model",
        deployment_generation=_GENERATION,
        qualified_capacity=2,
    )
    second = InterprocessModelAdmissionRegistry(root)
    with pytest.raises(ValueError, match="capacity drift"):
        second.controller_for(
            deployment_id="model",
            deployment_generation=_GENERATION,
            qualified_capacity=3,
        )
    first.close()
    second.close()

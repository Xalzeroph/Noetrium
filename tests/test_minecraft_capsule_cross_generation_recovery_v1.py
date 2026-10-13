from __future__ import annotations

from types import SimpleNamespace
import unittest

from noetrium_platform.composition.environment_capabilities.minecraft_local import (
    _DockerMinecraftCapsule,
    _MinecraftChildProcessInspectionIndeterminate,
)


class _Probe:
    docker_executable = "docker"

    @property
    def container_name(self):
        raise AssertionError("the current capsule must not be consulted during cross-capsule recovery")

    def __init__(self):
        self.commands = []
        self.runner = SimpleNamespace(run=self._run)

    def _run(self, command, *, timeout_seconds):
        self.commands.append((command, timeout_seconds))
        return SimpleNamespace(returncode=0, stdout="123|42\n", stderr="")


class PhysicalContainerScopeTests(unittest.TestCase):
    def test_foreign_live_capsule_uses_exact_selected_physical_id(self):
        parent = _Probe()
        child = SimpleNamespace(pid=123, start_identity="docker-exec:foreign-capsule:123:42")
        result = _DockerMinecraftCapsule._batch_alive_processes(
            parent, (child,), container_name="foreign-capsule",
        )
        self.assertEqual(result, (child,))
        self.assertEqual(parent.commands[0][0][2], "foreign-capsule")
        self.assertEqual(parent.commands[0][1], 10.0)

    def test_cross_capsule_process_generation_remains_fenced(self):
        parent = _Probe()
        child = SimpleNamespace(pid=123, start_identity="docker-exec:foreign-capsule:123:42")
        with self.assertRaises(_MinecraftChildProcessInspectionIndeterminate):
            _DockerMinecraftCapsule._batch_alive_processes(
                parent, (child,), container_name="other-capsule",
            )
        self.assertFalse(parent.commands)


if __name__ == "__main__":
    unittest.main()

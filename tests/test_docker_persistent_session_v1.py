from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.infrastructure.lifecycle.process.api import ProcessCommandResult
from noetrium_platform.infrastructure.lifecycle.session.api import PersistentSessionSpec
from noetrium_platform.infrastructure.lifecycle.session.runtime.binding import (
    DirectoryPersistentSessionBindingStore,
)
from noetrium_platform.infrastructure.lifecycle.session.runtime.docker_transport import (
    DockerPersistentSessionControl,
)
from noetrium_platform.infrastructure.lifecycle.session.runtime.manager import (
    PersistentSessionManager,
)


class _Handle:
    def __init__(self, result: ProcessCommandResult) -> None:
        self._result = result

    def result(self):
        return self._result


class _DockerRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.created = False
        self.transport_digest = ""
        self.spec: PersistentSessionSpec | None = None
    def _row(self) -> dict[str, object]:
        assert self.spec is not None
        return {
            "Id": "cid-123",
            "State": {"Running": True, "Pid": 4242},
            "Config": {
                "WorkingDir": self.spec.cwd,
                "Entrypoint": None,
                "Cmd": list(self.spec.command_argv),
                "Labels": {
                    "io.noetrium.persistent-session": "true",
                    "io.noetrium.persistent-session-name": self.spec.session_name,
                    "io.noetrium.persistent-session-spec": self.spec.digest(),
                    "io.noetrium.persistent-session-transport": self.transport_digest,
                },
            },
        }

    def execute(self, argv, **kwargs):
        del kwargs
        argv = tuple(argv)
        self.calls.append(argv)
        if argv[1:4] == ("image", "inspect", "--format"):
            return _Handle(ProcessCommandResult(0, b"sha256:image\n"))
        if argv[1:3] == ("info", "--format"):
            return _Handle(ProcessCommandResult(0, b"daemon-1\n"))
        if argv[1] == "inspect":
            target = argv[2]
            if not self.created and target != "cid-123":
                return _Handle(ProcessCommandResult(1, b"", b"Error: No such object"))
            return _Handle(ProcessCommandResult(
                0,
                json.dumps([self._row()]).encode(),
            ))
        if argv[1] == "run":
            self.created = True
            return _Handle(ProcessCommandResult(0, b"cid-123\n"))
        if argv[1:3] == ("rm", "-f"):
            self.created = False
            return _Handle(ProcessCommandResult(0, b"cid-123\n"))
        raise AssertionError(argv)


class DockerPersistentSessionTests(unittest.TestCase):
    def test_ensure_reuses_exact_container_generation(self):
        with TemporaryDirectory() as td:
            runner = _DockerRunner()
            control = DockerPersistentSessionControl(
                process_runner=runner,
                image="noetrium/control:test",
                binary_identity_digest="a" * 64,
                image_identity="sha256:image",
                daemon_identity="daemon-1",
            )
            spec = PersistentSessionSpec(
                "runtime-fabric-test",
                ("/usr/bin/python3", "-m", "runtime_controller"),
                "/opt/noetrium/release",
                "runtime-fabric",
                "b" * 64,
            )
            runner.transport_digest = control.identity_digest
            runner.spec = spec
            manager = PersistentSessionManager(
                control,
                DirectoryPersistentSessionBindingStore(Path(td) / "bindings"),
            )
            first = manager.ensure(spec)
            second = manager.ensure(spec)
            self.assertFalse(first.reused)
            self.assertTrue(second.reused)
            run_calls = [call for call in runner.calls if call[1] == "run"]
            self.assertEqual(len(run_calls), 1)
            self.assertEqual(
                first.snapshot.session_generation,
                second.snapshot.session_generation,
            )

            refs = manager.terminate(spec)
            self.assertTrue(any(ref.startswith("docker-session-killed:") for ref in refs))
            rm_calls = [call for call in runner.calls if call[1:3] == ("rm", "-f")]
            self.assertEqual(len(rm_calls), 1)
            self.assertEqual(rm_calls[0][-1], "cid-123")
            self.assertNotEqual(rm_calls[0][-1], spec.session_name)


if __name__ == "__main__":
    unittest.main()

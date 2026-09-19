from __future__ import annotations

from tests_support import frozen_runtime_manifest

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.infrastructure.lifecycle.session.api import RuntimeControllerCommand
from noetrium_platform.infrastructure.lifecycle.session.runtime import RuntimePersistentSessionHost
from noetrium_platform.infrastructure.lifecycle.session.api import PersistentSessionDrift, PersistentSessionSpec
from noetrium_platform.infrastructure.lifecycle.session.runtime import (
    DirectoryPersistentSessionBindingStore,
    PersistentSessionManager,
    TmuxPersistentSessionControl,
    TmuxCommandResult,
)


class FakeTmuxRunner:
    def __init__(self) -> None:
        self.sessions: dict[str, tuple[int, str, str]] = {}
        self.calls: list[tuple[tuple[str, ...], dict[str, str]]] = []
        self.effects: list[str] = []
        self.next_pid = 700

    def run(self, argv, *, environment, effect="unknown"):
        argv = tuple(argv)
        self.calls.append((argv, dict(environment)))
        self.effects.append(effect)
        args = argv[5:]  # /usr/bin/tmux -L label
        if args[0] == "display-message":
            name = args[args.index("-t") + 1].lstrip("=").split(":", 1)[0]
            if name not in self.sessions:
                return TmuxCommandResult(1, "", "can't find session")
            pid, command, cwd = self.sessions[name]
            return TmuxCommandResult(0, f"{name}\t{pid}\t0\t{command}\t{cwd}\n", "")
        if args[0] == "new-session":
            name = args[args.index("-s") + 1]
            if name in self.sessions:
                return TmuxCommandResult(1, "", "duplicate session")
            command = args[-1]
            self.next_pid += 1
            self.sessions[name] = (self.next_pid, command, args[args.index("-c") + 1])
            return TmuxCommandResult(0, "", "")
        if args[0] == "kill-session":
            name = args[args.index("-t") + 1].lstrip("=")
            self.sessions.pop(name, None)
            return TmuxCommandResult(0, "", "")
        raise AssertionError(args)


def manifest():
    h = "a" * 64
    return frozen_runtime_manifest(release_digest=h, prompt_generation_digest=h, prompt_promotion_digest=h, role_model_manifest_digest=h, qualified_deployment_digests=(h,), target_host_identity_digest=h, experiment_spec_digest=h, config_digests=(("state_backend", h),))


class TmuxServerSessionTests(unittest.TestCase):
    def manager(self, root: Path, runner: FakeTmuxRunner):
        cli = TmuxPersistentSessionControl(
            tmux_executable="/usr/bin/tmux",
            server_label="rp-test",
            socket_directory="/tmp",
            runner=runner,
        )
        return PersistentSessionManager(cli, DirectoryPersistentSessionBindingStore(root / "bindings"))

    def test_exact_binding_is_reused_without_second_tmux_create(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            runner = FakeTmuxRunner()
            manager = self.manager(root, runner)
            spec = PersistentSessionSpec(
                "rp-run-abc", ("/usr/bin/python3", "-m", "runner"), "/tmp", "control-1", "b" * 64
            )
            first = manager.ensure(spec)
            second = manager.ensure(spec)
            self.assertFalse(first.reused)
            self.assertTrue(second.reused)
            creates = [call for call, _ in runner.calls if "new-session" in call]
            self.assertEqual(len(creates), 1)
            self.assertEqual(first.snapshot.session_name, spec.session_name)

    def test_same_session_name_cannot_be_rebound_to_new_code(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            runner = FakeTmuxRunner()
            manager = self.manager(root, runner)
            old = PersistentSessionSpec("rp-run", ("/bin/echo", "old"), "/tmp", "c", "c" * 64)
            manager.ensure(old)
            changed = PersistentSessionSpec("rp-run", ("/bin/echo", "new"), "/tmp", "c", "c" * 64)
            with self.assertRaises(PersistentSessionDrift):
                manager.ensure(changed)
            creates = [call for call, _ in runner.calls if "new-session" in call]
            self.assertEqual(len(creates), 1)

    def test_bind_once_refuses_second_different_binding_without_overwrite(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            store = DirectoryPersistentSessionBindingStore(root / "bindings")
            first = PersistentSessionSpec("rp-race", ("/bin/echo", "one"), "/tmp", "c", "2" * 64)
            second = PersistentSessionSpec("rp-race", ("/bin/echo", "two"), "/tmp", "c", "2" * 64)
            from noetrium_platform.infrastructure.lifecycle.session.api import PersistentSessionBinding
            a = PersistentSessionBinding.from_spec(first, "3" * 64)
            b = PersistentSessionBinding.from_spec(second, "3" * 64)
            self.assertEqual(store.bind_once(a), a)
            self.assertEqual(store.bind_once(b), a)
            self.assertEqual(store.read("rp-race"), a)

    def test_binding_checksum_rejects_manual_edit(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            runner = FakeTmuxRunner()
            manager = self.manager(root, runner)
            spec = PersistentSessionSpec("rp-run", ("/bin/echo", "ok"), "/tmp", "c", "d" * 64)
            manager.ensure(spec)
            self.assertIn("mutation", runner.effects)
            path = root / "bindings" / "rp-run.json"
            doc = json.loads(path.read_text())
            doc["payload"]["spec"]["control_id"] = "tampered"
            path.write_text(json.dumps(doc))
            with self.assertRaises(Exception):
                manager.inspect(spec)

    def test_tmux_command_is_generated_from_argv_not_arbitrary_shell_fragment(self):
        with TemporaryDirectory() as td:
            runner = FakeTmuxRunner()
            manager = self.manager(Path(td), runner)
            spec = PersistentSessionSpec(
                "rp-safe", ("/bin/echo", "a; rm -rf /", "$(touch bad)"), "/tmp", "c", "e" * 64
            )
            manager.ensure(spec)
            create = next(call for call, _ in runner.calls if "new-session" in call)
            pane_command = create[-1]
            self.assertEqual(pane_command, "exec /usr/bin/env -i /bin/echo 'a; rm -rf /' '$(touch bad)'")
            self.assertNotIn("shell=True", repr(runner.calls))

    def test_controller_process_environment_is_frozen_into_pane_command_and_spec_digest(self):
        with TemporaryDirectory() as td:
            runner = FakeTmuxRunner()
            manager = self.manager(Path(td), runner)
            env = (("CUDA_VISIBLE_DEVICES", "0,1"), ("PATH", "/srv/bin"))
            spec = PersistentSessionSpec(
                "rp-env",
                ("/bin/echo", "x"),
                "/tmp",
                "c",
                "6" * 64,
                process_environment=env,
            )
            manager.ensure(spec)
            create = next(call for call, _ in runner.calls if "new-session" in call)
            self.assertEqual(
                create[-1],
                "exec /usr/bin/env -i CUDA_VISIBLE_DEVICES=0,1 PATH=/srv/bin /bin/echo x",
            )
            changed = PersistentSessionSpec(
                "rp-env",
                ("/bin/echo", "x"),
                "/tmp",
                "c",
                "6" * 64,
                process_environment=(("CUDA_VISIBLE_DEVICES", "2"), ("PATH", "/srv/bin")),
            )
            self.assertNotEqual(spec.digest(), changed.digest())

    def test_runtime_host_session_name_binds_control_and_manifest(self):
        with TemporaryDirectory() as td:
            runner = FakeTmuxRunner()
            host = RuntimePersistentSessionHost(self.manager(Path(td), runner))
            cmd = RuntimeControllerCommand(
                ("/usr/bin/python3", "-m", "server.entry"),
                "/srv/research",
                launcher_binary_sha256="a" * 64,
            )
            report = host.ensure(manifest(), control_id="paper-1/run A", command=cmd)
            self.assertTrue(report.snapshot.session_name.startswith("rp-paper-1-run-A-"))
            self.assertIn(manifest().digest()[:12], report.snapshot.session_name)
            self.assertEqual(report.attach_argv[-2:], ("-t", f"={report.snapshot.session_name}"))

    def test_manual_same_name_tmux_session_with_wrong_command_is_rejected(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            runner = FakeTmuxRunner()
            manager = self.manager(root, runner)
            spec = PersistentSessionSpec("rp-run", ("/bin/echo", "expected"), "/tmp", "c", "f" * 64)
            manager.ensure(spec)
            pid, _, cwd = runner.sessions[spec.session_name]
            runner.sessions[spec.session_name] = (pid, "exec /bin/echo wrong", cwd)
            with self.assertRaises(PersistentSessionDrift):
                manager.ensure(spec)

    def test_tmux_transport_identity_drift_is_rejected(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            runner = FakeTmuxRunner()
            first = self.manager(root, runner)
            spec = PersistentSessionSpec("rp-run", ("/bin/echo", "expected"), "/tmp", "c", "1" * 64)
            first.ensure(spec)
            changed_cli = TmuxPersistentSessionControl(
                tmux_executable="/opt/tmux",
                server_label="rp-test",
                socket_directory="/tmp",
                runner=runner,
            )
            changed = PersistentSessionManager(changed_cli, DirectoryPersistentSessionBindingStore(root / "bindings"))
            with self.assertRaises(PersistentSessionDrift):
                changed.ensure(spec)

    def test_attach_requires_exact_durable_binding_and_live_snapshot(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            runner = FakeTmuxRunner()
            manager = self.manager(root, runner)
            spec = PersistentSessionSpec("rp-attach", ("/bin/echo", "attached"), "/tmp", "c", "8" * 64)
            manager.ensure(spec)
            argv = manager.attach(spec)
            self.assertEqual(argv[-2:], ("-t", "=rp-attach"))

            unbound = PersistentSessionSpec("rp-unbound", ("/bin/echo", "x"), "/tmp", "c", "9" * 64)
            with self.assertRaises(PersistentSessionDrift):
                manager.attach(unbound)

    def test_attach_rejects_live_command_drift_before_materializing_tty(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            runner = FakeTmuxRunner()
            manager = self.manager(root, runner)
            spec = PersistentSessionSpec("rp-attach-drift", ("/bin/echo", "expected"), "/tmp", "c", "a" * 64)
            manager.ensure(spec)
            pid, _, cwd = runner.sessions[spec.session_name]
            runner.sessions[spec.session_name] = (pid, "exec /bin/echo changed", cwd)
            with self.assertRaises(PersistentSessionDrift):
                manager.attach(spec)


if __name__ == "__main__":
    unittest.main()

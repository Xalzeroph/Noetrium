from __future__ import annotations

from tests_support import frozen_runtime_manifest

from pathlib import Path
import hashlib
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.infrastructure.lifecycle.server.lifecycle.runtime import (
    ImmutableServerReleaseLayout,
    ServerReleaseLayoutError,
    ServerRuntimeBootstrap,
    ServerRuntimeLaunchManifestMismatch,
    ServerSessionPolicyMismatch,
)
from noetrium_platform.foundation.governance.release.runtime.active_pin_store import ActiveReleasePinStore
from noetrium_platform.infrastructure.lifecycle.host.bootstrap.runtime import DirectoryServerBootstrapStateStore, ServerBootstrapTransaction
from noetrium_platform.foundation.governance.release.api import ActiveReleasePinned
from noetrium_platform.infrastructure.lifecycle.session.api import ServerSessionPolicy
from noetrium_platform.infrastructure.lifecycle.session.runtime import (
    DirectoryPersistentSessionBindingStore,
    PersistentSessionManager,
    TmuxPersistentSessionControl,
    TmuxCommandResult,
    RuntimePersistentSessionHost,
)


class Runner:
    def __init__(self):
        self.sessions = {}
        self.calls = []

    def run(self, argv, *, environment, effect="unknown"):
        del effect
        argv = tuple(argv); self.calls.append(argv); args = argv[5:]
        if args[0] == "display-message":
            name = args[args.index("-t") + 1].lstrip("=").split(":", 1)[0]
            if name not in self.sessions:
                return TmuxCommandResult(1, "", "missing")
            command, cwd = self.sessions[name]
            return TmuxCommandResult(0, f"{name}\t900\t0\t{command}\t{cwd}\n", "")
        if args[0] == "new-session":
            name = args[args.index("-s") + 1]; self.sessions[name] = (args[-1], args[args.index("-c") + 1])
            return TmuxCommandResult(0, "", "")
        if args[0] == "kill-session":
            return TmuxCommandResult(0, "", "")
        raise AssertionError(args)


def manifest(
    release_digest: str,
    policy_digest: str,
    *,
    command_argv: tuple[str, ...] = ("/usr/bin/python3", "-m", "server_runtime_entry"),
):
    h = "b" * 64
    return frozen_runtime_manifest(release_digest=release_digest, prompt_generation_digest=h, prompt_promotion_digest=h, role_model_manifest_digest=h, qualified_deployment_digests=(h,), target_host_identity_digest=h, experiment_spec_digest=h, command_argv=command_argv, config_digests=(("server_session", policy_digest),))


class ServerRuntimeBootstrapTests(unittest.TestCase):
    def fixture(self, base: Path):
        runner = Runner()
        tmux_binary = base / "tmux"
        tmux_binary.write_bytes(b"verified-tmux-test-binary")
        tmux_digest = hashlib.sha256(tmux_binary.read_bytes()).hexdigest()
        cli = TmuxPersistentSessionControl(
            tmux_executable=str(tmux_binary),
            binary_identity_digest=tmux_digest,
            runner=runner,
        )
        sessions = PersistentSessionManager(
            cli,
            DirectoryPersistentSessionBindingStore(base / "session-bindings"),
        )
        host = RuntimePersistentSessionHost(sessions)
        policy = ServerSessionPolicy("tmux", host.transport_identity_digest)
        pins = ActiveReleasePinStore(base / "release-pins")
        transaction = ServerBootstrapTransaction(
            DirectoryServerBootstrapStateStore(base / "server-bootstrap"),
            pins,
            sessions,
        )
        bootstrap = ServerRuntimeBootstrap(ImmutableServerReleaseLayout(base), host, transaction, policy)
        return runner, policy, bootstrap, pins

    def test_controller_always_runs_from_content_addressed_release_directory(self):
        with TemporaryDirectory() as td:
            base = Path(td); release = "a" * 64
            release_dir = base / "releases" / release; release_dir.mkdir(parents=True)
            runner, policy, bootstrap, _ = self.fixture(base)
            report = bootstrap.ensure_controller(
                manifest(release, policy.digest()),
                control_id="paper-1-prod",
            )
            self.assertEqual(report.release_dir, release_dir)
            self.assertEqual(report.server_session_policy_digest, policy.digest())
            create = next(call for call in runner.calls if "new-session" in call)
            self.assertEqual(create[create.index("-c") + 1], str(release_dir))
            self.assertIn("/usr/bin/python3", create[-1])

    def test_missing_release_directory_fails_before_tmux_side_effect(self):
        with TemporaryDirectory() as td:
            base = Path(td); runner, policy, bootstrap, _ = self.fixture(base)
            with self.assertRaises(ServerReleaseLayoutError):
                bootstrap.ensure_controller(
                    manifest("c" * 64, policy.digest()),
                    control_id="prod",
                )
            self.assertFalse(any("new-session" in call for call in runner.calls))

    def test_manifest_without_exact_tmux_policy_is_rejected_before_side_effect(self):
        with TemporaryDirectory() as td:
            base = Path(td); release = "d" * 64
            (base / "releases" / release).mkdir(parents=True)
            runner, _, bootstrap, _ = self.fixture(base)
            with self.assertRaises(ServerSessionPolicyMismatch):
                bootstrap.ensure_controller(
                    manifest(release, "f" * 64),
                    control_id="prod",
                )
            self.assertFalse(any("new-session" in call for call in runner.calls))

    def test_controller_environment_must_match_the_frozen_manifest_before_side_effect(self):
        with TemporaryDirectory() as td:
            base = Path(td); release = "e" * 64
            (base / "releases" / release).mkdir(parents=True)
            runner, policy, bootstrap, _ = self.fixture(base)
            with self.assertRaises(ServerRuntimeLaunchManifestMismatch):
                bootstrap.ensure_controller(
                    manifest(release, policy.digest()),
                    control_id="prod",
                    controller_environment=(("CUDA_VISIBLE_DEVICES", "0"),),
                )
            self.assertFalse(any("new-session" in call for call in runner.calls))

    def test_new_release_digest_cannot_reuse_old_release_session_binding(self):
        with TemporaryDirectory() as td:
            base = Path(td); releases = ["d" * 64, "e" * 64]
            for digest in releases: (base / "releases" / digest).mkdir(parents=True)
            runner, policy, bootstrap, _ = self.fixture(base)
            first = bootstrap.ensure_controller(
                manifest(releases[0], policy.digest()), control_id="prod"
            )
            second = bootstrap.ensure_controller(
                manifest(releases[1], policy.digest()), control_id="prod"
            )
            self.assertNotEqual(first.session.snapshot.session_name, second.session.snapshot.session_name)
            self.assertEqual(len([c for c in runner.calls if "new-session" in c]), 2)

    def test_active_run_pins_release_and_cleanup_guard_refuses_delete(self):
        with TemporaryDirectory() as td:
            base = Path(td); release = "9" * 64
            (base / "releases" / release).mkdir(parents=True)
            _, policy, bootstrap, pins = self.fixture(base)
            runtime_manifest = manifest(release, policy.digest())
            bootstrap.ensure_controller(
                runtime_manifest, control_id="prod"
            )
            active = pins.active_for_release(release)
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0].runtime_manifest_digest, runtime_manifest.digest())
            with self.assertRaises(ActiveReleasePinned):
                pins.assert_unpinned(release)

    def test_new_release_can_be_pinned_without_mutating_old_release_pin(self):
        with TemporaryDirectory() as td:
            base = Path(td); releases = ["7" * 64, "8" * 64]
            for release in releases: (base / "releases" / release).mkdir(parents=True)
            _, policy, bootstrap, pins = self.fixture(base)
            for release in releases:
                bootstrap.ensure_controller(
                    manifest(release, policy.digest()), control_id="prod"
                )
            self.assertEqual(len(pins.all()), 2)
            self.assertEqual({p.release_digest for p in pins.all()}, set(releases))


if __name__ == "__main__": unittest.main()

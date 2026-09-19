from __future__ import annotations

from tests_support import frozen_runtime_manifest

from pathlib import Path
import hashlib
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.infrastructure.lifecycle.server.lifecycle.runtime import ImmutableServerReleaseLayout, ServerRuntimeBootstrap, ServerSessionPolicyMismatch
from noetrium_platform.foundation.governance.release.runtime.active_pin_store import ActiveReleasePinStore
from noetrium_platform.infrastructure.lifecycle.host.bootstrap.runtime import DirectoryServerBootstrapStateStore, ServerBootstrapTransaction
from noetrium_platform.infrastructure.lifecycle.session.api import PersistentSessionEffectUncertain, PersistentSessionSpec, ServerSessionPolicy
from noetrium_platform.infrastructure.lifecycle.session.runtime import (
    BoundPersistentSessionStatusProbe, DirectoryPersistentSessionBindingStore,
    PersistentSessionManager, TmuxPersistentSessionControl, TmuxBinaryIdentityMismatch, TmuxCommandFailed, TmuxCommandResult,
    RuntimePersistentSessionHost,
)
from noetrium_platform.infrastructure.lifecycle.session.runtime.tmux_contracts import TmuxCommandTimeout

TEST_TMUX_EXECUTABLE = "/definitely/missing/tmux"


class Runner:
    def __init__(self, fail=False): self.sessions={}; self.fail=fail
    def run(self, argv, *, environment, effect="unknown"):
        del effect
        if self.fail: raise TmuxCommandTimeout('simulated tmux socket timeout')
        args=tuple(argv)[5:]
        if args[0]=='display-message':
            name=args[args.index('-t')+1].lstrip('=').split(':', 1)[0]
            if name not in self.sessions: return TmuxCommandResult(1,'','missing')
            command,cwd=self.sessions[name]; return TmuxCommandResult(0,f'{name}\t88\t0\t{command}\t{cwd}\n','')
        if args[0]=='new-session': self.sessions[args[args.index('-s')+1]]=(args[-1],args[args.index('-c')+1]); return TmuxCommandResult(0,'','')
        if args[0]=='kill-session': return TmuxCommandResult(0,'','')
        raise AssertionError(args)


def manifest(release, policy):
    h='a'*64
    return frozen_runtime_manifest(release_digest=release, prompt_generation_digest=h, prompt_promotion_digest=h, role_model_manifest_digest=h, qualified_deployment_digests=(h,), target_host_identity_digest=h, experiment_spec_digest=h, config_digests=(("server_session",policy),))


class TmuxTransportIdentityTests(unittest.TestCase):
    def test_binary_bytes_change_transport_identity_and_are_locally_verified(self):
        with TemporaryDirectory() as td:
            binary = Path(td) / "tmux"
            binary.write_bytes(b"v1")
            a = TmuxPersistentSessionControl(tmux_executable=str(binary), runner=Runner())
            binary.write_bytes(b"v2")
            b = TmuxPersistentSessionControl(tmux_executable=str(binary), runner=Runner())
            self.assertNotEqual(a.identity_digest, b.identity_digest)
            self.assertTrue(a.identity_verified)
            self.assertTrue(b.identity_verified)

    def test_configured_binary_digest_cannot_claim_verification_when_bytes_disagree(self):
        with TemporaryDirectory() as td:
            binary = Path(td) / "tmux"
            binary.write_bytes(b"actual")
            with self.assertRaises(TmuxBinaryIdentityMismatch):
                TmuxPersistentSessionControl(
                    tmux_executable=str(binary),
                    binary_identity_digest="1" * 64,
                    runner=Runner(),
                )

    def test_observation_timeout_policy_does_not_change_transport_identity(self):
        a = TmuxPersistentSessionControl(
            tmux_executable=TEST_TMUX_EXECUTABLE,
            binary_identity_digest="6" * 64,
            command_timeout_s=1.0,
            runner=Runner(),
        )
        b = TmuxPersistentSessionControl(
            tmux_executable=TEST_TMUX_EXECUTABLE,
            binary_identity_digest="6" * 64,
            command_timeout_s=30.0,
            runner=Runner(),
        )
        self.assertEqual(a.identity_digest, b.identity_digest)

    def test_tmux_command_disables_user_configuration(self):
        control = TmuxPersistentSessionControl(
            tmux_executable=TEST_TMUX_EXECUTABLE,
            binary_identity_digest="6" * 64,
            runner=Runner(),
        )
        self.assertEqual(control.commands.argv("list-sessions")[:5], (TEST_TMUX_EXECUTABLE, "-f", "/dev/null", "-L", "noetrium"))

    def test_production_bootstrap_rejects_unverified_tmux_binary(self):
        with TemporaryDirectory() as td:
            base=Path(td); release='b'*64; (base/'releases'/release).mkdir(parents=True)
            cli=TmuxPersistentSessionControl(tmux_executable='/definitely/missing/tmux',runner=Runner())
            sessions=PersistentSessionManager(cli,DirectoryPersistentSessionBindingStore(base/'bindings'))
            host=RuntimePersistentSessionHost(sessions)
            pins=ActiveReleasePinStore(base/'pins')
            transaction=ServerBootstrapTransaction(DirectoryServerBootstrapStateStore(base/'bootstrap'),pins,sessions)
            with self.assertRaises(ServerSessionPolicyMismatch):
                ServerRuntimeBootstrap(ImmutableServerReleaseLayout(base),host,transaction)

    def test_non_missing_tmux_error_is_not_misclassified_as_absent(self):
        class PermissionRunner:
            def run(self, argv, *, environment, effect="unknown"):
                del effect
                return TmuxCommandResult(2, "", "permission denied opening tmux socket")

        control = TmuxPersistentSessionControl(
            tmux_executable=TEST_TMUX_EXECUTABLE,
            binary_identity_digest="9" * 64,
            runner=PermissionRunner(),
        )
        with self.assertRaises(TmuxCommandFailed):
            control.inspect("rp-x")

    def test_missing_tmux_server_socket_is_an_absent_session(self):
        class MissingSocketRunner:
            def run(self, argv, *, environment, effect="unknown"):
                del effect
                return TmuxCommandResult(1, "", "error connecting to /tmp/tmux-1000/noetrium (No such file or directory)")

        control = TmuxPersistentSessionControl(
            tmux_executable=TEST_TMUX_EXECUTABLE,
            binary_identity_digest="a" * 64,
            runner=MissingSocketRunner(),
        )
        self.assertFalse(control.inspect("rp-x").exists)

    def test_create_timeout_is_typed_as_uncertain_external_effect(self):
        control = TmuxPersistentSessionControl(
            tmux_executable=TEST_TMUX_EXECUTABLE,
            binary_identity_digest="8" * 64,
            runner=Runner(fail=True),
        )
        spec = PersistentSessionSpec("rp-uncertain", ("/bin/echo", "x"), "/tmp", "c", "7" * 64)
        with self.assertRaises(PersistentSessionEffectUncertain) as ctx:
            control.create_detached(spec)
        self.assertEqual(ctx.exception.operation, "create")
        self.assertEqual(ctx.exception.session_name, "rp-uncertain")

    def test_status_probe_turns_tmux_timeout_into_observational_unavailable(self):
        with TemporaryDirectory() as td:
            root=Path(td); runner=Runner(); cli=TmuxPersistentSessionControl(tmux_executable=TEST_TMUX_EXECUTABLE,binary_identity_digest='3'*64,runner=runner)
            bindings=DirectoryPersistentSessionBindingStore(root/'bindings')
            manager=PersistentSessionManager(cli,bindings)
            spec=PersistentSessionSpec('rp-x',('/bin/echo','x'),'/tmp','c','4'*64); manager.ensure(spec)
            failing=TmuxPersistentSessionControl(tmux_executable=TEST_TMUX_EXECUTABLE,binary_identity_digest='3'*64,runner=Runner(fail=True))
            observation=BoundPersistentSessionStatusProbe(failing,bindings,spec.session_name).observe()
            self.assertEqual(observation.state.value,'unavailable')
            self.assertIn('TmuxCommandTimeout',observation.summary)


if __name__=='__main__': unittest.main()

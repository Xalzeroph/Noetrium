from __future__ import annotations

from runtime_manager_test_support import make_runtime_control_store
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.infrastructure.reliability.forensics.runtime.diagnostic_adapter import ForensicDiagnosticEvidence
from noetrium_platform.evidence.observability.status.runtime import PlatformStatusService
from noetrium_platform.infrastructure.reliability.diagnostics.runtime.status_projection import ForensicStatusProbe
from noetrium_platform.infrastructure.lifecycle.launch_control import RuntimeControlStore
from tests_support import recovery_lease_state
from noetrium_platform.infrastructure.reliability.recovery.composition import compose_recovery_lease_status_probe
from noetrium_platform.infrastructure.lifecycle.launch_control.status_readers import RuntimeControlStatusReader
from noetrium_platform.infrastructure.lifecycle.launch_control.runtime_transaction_status import RuntimeTransactionStatusProbe
from noetrium_platform.infrastructure.lifecycle.session.api import PersistentSessionSpec
from noetrium_platform.infrastructure.lifecycle.session.runtime import (
    BoundPersistentSessionStatusProbe,
    PersistentSessionHealthProbe,
    DirectoryPersistentSessionBindingStore,
    PersistentSessionManager,
    TmuxPersistentSessionControl,
    TmuxCommandResult,
)


class Runner:
    def __init__(self): self.sessions = {}
    def run(self, argv, *, environment, effect="unknown"):
        del effect
        args=tuple(argv)[5:]
        if args[0]=='display-message':
            name=args[args.index('-t')+1].lstrip('=').split(':', 1)[0]
            if name not in self.sessions: return TmuxCommandResult(1,'','missing')
            pid,cmd,cwd=self.sessions[name]; return TmuxCommandResult(0,f'{name}\t{pid}\t0\t{cmd}\t{cwd}\n','')
        if args[0]=='new-session':
            name=args[args.index('-s')+1]; self.sessions[name]=(1234,args[-1],args[args.index('-c')+1]); return TmuxCommandResult(0,'','')
        if args[0]=='kill-session': self.sessions.clear(); return TmuxCommandResult(0,'','')
        raise AssertionError(args)


class TmuxJoinedRuntimeStatusTests(unittest.TestCase):
    def build(self, root: Path, *, kill_tmux: bool = False):
        runtime=make_runtime_control_store(root/'runtime.json'); runtime.create('ctl','manifest')
        runner=Runner(); cli=TmuxPersistentSessionControl(tmux_executable='/usr/bin/tmux',runner=runner)
        bindings=DirectoryPersistentSessionBindingStore(root/'bindings')
        manager=PersistentSessionManager(cli,bindings)
        spec=PersistentSessionSpec('rp-prod',('/bin/echo','controller'),'/tmp','ctl','a'*64)
        manager.ensure(spec)
        if kill_tmux: runner.sessions.clear()
        probe=BoundPersistentSessionStatusProbe(cli,bindings,spec.session_name)
        forensics=ForensicStore(root/'forensics')
        service=PlatformStatusService((
            PersistentSessionHealthProbe(probe),
            RuntimeTransactionStatusProbe(RuntimeControlStatusReader(runtime.state_store, runtime.history)),
            compose_recovery_lease_status_probe(recovery_lease_state(root/'lease.json')),
            ForensicStatusProbe(ForensicDiagnosticEvidence(forensics)),
        ))
        return service,forensics

    def test_exact_tmux_controller_is_visible_without_becoming_runtime_authority(self):
        with TemporaryDirectory() as td:
            service,store=self.build(Path(td))
            try:
                data=service.snapshot().to_dict()
                session=next(x for x in data['subsystems'] if x['subsystem']=='server_session')
                self.assertEqual(session['state'],'ready')
                self.assertIn('exact tmux controller pid=',session['summary'])
                self.assertEqual(session['reason_codes'],[])
            finally: store.close()

    def test_missing_tmux_is_operational_degradation_not_scientific_failure(self):
        with TemporaryDirectory() as td:
            service,store=self.build(Path(td),kill_tmux=True)
            try:
                data=service.snapshot().to_dict()
                self.assertEqual(data['status'],'degraded_operational')
                session=next(x for x in data['subsystems'] if x['subsystem']=='server_session')
                self.assertEqual(session['state'],'degraded_operational')
                self.assertIn('must be checked separately',session['summary'])
                self.assertEqual(session['reason_codes'],['session_missing'])
            finally: store.close()

    def test_status_detects_current_spec_drift_instead_of_reusing_old_binding(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            runner = Runner()
            cli = TmuxPersistentSessionControl(tmux_executable='/usr/bin/tmux', runner=runner)
            bindings = DirectoryPersistentSessionBindingStore(root/'bindings')
            manager = PersistentSessionManager(cli, bindings)
            spec = PersistentSessionSpec('rp-profile',('/bin/echo','controller'),'/tmp','ctl','a'*64)
            manager.ensure(spec)
            changed = PersistentSessionSpec('rp-profile',('/bin/echo','controller'),'/tmp','ctl','b'*64)
            probe = BoundPersistentSessionStatusProbe(
                cli,
                bindings,
                spec.session_name,
                expected_spec=changed,
            )
            observation = probe.observe()
            self.assertEqual(observation.state.value, 'drift')
            self.assertEqual(observation.reason_code, 'binding_drift')


if __name__=='__main__': unittest.main()

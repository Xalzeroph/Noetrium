from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.infrastructure.lifecycle.session.api import PersistentSessionDrift, PersistentSessionSpec
from noetrium_platform.infrastructure.lifecycle.session.runtime import DirectoryPersistentSessionBindingStore, PersistentSessionManager, TmuxPersistentSessionControl, TmuxCommandResult

TEST_TMUX_EXECUTABLE = "/definitely/missing/tmux"


class Runner:
    def __init__(self): self.sessions={}
    def run(self, argv, *, environment, effect="unknown"):
        del effect
        args=tuple(argv)[5:]
        if args[0]=='display-message':
            name=args[args.index('-t')+1].lstrip('=').split(':', 1)[0]
            if name not in self.sessions: return TmuxCommandResult(1,'','missing')
            cmd,cwd=self.sessions[name]
            return TmuxCommandResult(0,f'{name}\t55\t0\t{cmd}\t{cwd}\n','')
        if args[0]=='new-session':
            self.sessions[args[args.index('-s')+1]]=(args[-1],args[args.index('-c')+1]); return TmuxCommandResult(0,'','')
        if args[0]=='kill-session': return TmuxCommandResult(0,'','')
        raise AssertionError(args)


class TmuxCwdIdentityTests(unittest.TestCase):
    def test_same_name_and_command_but_different_pane_cwd_is_drift(self):
        with TemporaryDirectory() as td:
            root=Path(td); runner=Runner(); cli=TmuxPersistentSessionControl(tmux_executable=TEST_TMUX_EXECUTABLE,binary_identity_digest='1'*64,runner=runner)
            manager=PersistentSessionManager(cli,DirectoryPersistentSessionBindingStore(root/'bindings'))
            spec=PersistentSessionSpec('rp-x',('/bin/echo','x'),'/srv/releases/a','ctl','a'*64,'b'*64)
            manager.ensure(spec)
            cmd,_=runner.sessions['rp-x']; runner.sessions['rp-x']=(cmd,'/srv/releases/other')
            with self.assertRaises(PersistentSessionDrift): manager.ensure(spec)


if __name__=='__main__': unittest.main()

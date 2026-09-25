from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.infrastructure.lifecycle.session.api import RuntimeControllerCommand
from noetrium_platform.infrastructure.lifecycle.session.api import PersistentSessionSpec
from noetrium_platform.infrastructure.lifecycle.session.api import PersistentSessionSpec


class ControllerLauncherIdentityTests(unittest.TestCase):
    def test_launcher_binary_bytes_change_frozen_controller_identity(self):
        with TemporaryDirectory() as td:
            root=Path(td); launcher=root/'python'; launcher.write_bytes(b'v1')
            a=RuntimeControllerCommand((str(launcher),'-m','entry'),str(root))
            launcher.write_bytes(b'v2')
            b=RuntimeControllerCommand((str(launcher),'-m','entry'),str(root))
            self.assertNotEqual(a.launcher_binary_sha256,b.launcher_binary_sha256)
            self.assertNotEqual(a.digest(),b.digest())

    def test_persistent_spec_digest_binds_controller_command_identity(self):
        base=dict(session_name='rp-x',command_argv=('/bin/echo','x'),cwd='/tmp',control_id='c',runtime_manifest_digest='a'*64)
        a=PersistentSessionSpec(**base,command_identity_digest='1'*64)
        b=PersistentSessionSpec(**base,command_identity_digest='2'*64)
        self.assertNotEqual(a.digest(),b.digest())

    def test_relative_controller_launcher_is_rejected(self):
        with self.assertRaises(ValueError):
            RuntimeControllerCommand(('python','-m','entry'),'/tmp',launcher_binary_sha256='1'*64)


if __name__=='__main__': unittest.main()

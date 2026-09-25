from __future__ import annotations

from runtime_manager_test_support import make_runtime_control_store
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.infrastructure.lifecycle.launch_control import ExactRuntimeController, RuntimeAction, RuntimeControlStore, exact_runtime_plan
from tests_support import frozen_runtime_manifest


def manifest():
    return frozen_runtime_manifest(qualified_deployment_digests=('d',), config_digests=(('c','h'),))


class Adapter:
    def execute(self, action, manifest): return ()


class Guard:
    def __init__(self): self.events=[]
    def before_action(self, action, manifest): self.events.append(('before',action))
    def after_success(self, action, manifest): self.events.append(('after',action))


class RuntimeActionGuardV166Tests(unittest.TestCase):
    def test_guard_wraps_each_exact_runtime_action_without_owning_action_logic(self):
        with TemporaryDirectory() as td:
            guard=Guard()
            ExactRuntimeController(make_runtime_control_store(Path(td)/'runtime.json'),Adapter()).run(
                manifest(),control_id='ctl',action_guard=guard
            )
            actions=tuple(step.action for step in exact_runtime_plan().steps)
            self.assertEqual(tuple(x[1] for x in guard.events[::2]),actions)
            self.assertTrue(all(kind=='before' for kind,_ in guard.events[::2]))
            self.assertTrue(all(kind=='after' for kind,_ in guard.events[1::2]))

if __name__=='__main__': unittest.main()

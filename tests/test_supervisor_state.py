from pathlib import Path
import json
import tempfile
import unittest
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity
from noetrium_platform.capabilities.model.serving.api import ModelPhase, ModelRunState
from noetrium_platform.capabilities.model.serving.runtime import ModelSupervisor
from noetrium_platform.capabilities.model.serving.providers.supervisor_storage import FileModelSupervisorStateStore

class SupervisorStateTests(unittest.TestCase):
    def test_atomic_state_file_tracks_phase(self):
        with tempfile.TemporaryDirectory() as td:
            ident=ImmutableModelIdentity("m","id","r","sglang","v","bfloat16",None,262144)
            s=ModelSupervisor(FileModelSupervisorStateStore(Path(td)/"state.json"), ModelRunState.initial("run", ident, "d"*64))
            s.transition(ModelPhase.INVENTORY)
            payload=json.loads((Path(td)/"state.json").read_text())
            self.assertEqual(payload["phase"], "inventory")

if __name__ == "__main__": unittest.main()

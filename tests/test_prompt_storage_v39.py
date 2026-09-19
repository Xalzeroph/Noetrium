from prompt_os_test_support import make_prompt_registry
from pathlib import Path
import tempfile,unittest
from noetrium_platform.capabilities.model.request.prompt.runtime import DurablePromptRegistry,default_block_policies,default_output_schemas,default_prompt_specs

class PromptStorageV39Tests(unittest.TestCase):
    def test_generation_stage_and_load_roundtrip_exact_digests(self):
        with tempfile.TemporaryDirectory() as td:
            reg=make_prompt_registry(Path(td)); m=reg.stage('g1',default_prompt_specs(),default_block_policies(),default_output_schemas()); loaded,bundles=reg.generation_store.load('g1')
            self.assertEqual(m,loaded); self.assertEqual(len(bundles),4)
    def test_stale_stage_directory_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); reg=make_prompt_registry(root); (root/'generations'/'g1.tmp').mkdir(parents=True)
            with self.assertRaises(Exception): reg.stage('g1',default_prompt_specs(),default_block_policies(),default_output_schemas())

if __name__=='__main__':unittest.main()

from pathlib import Path
import sys, unittest
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from noetrium_platform.foundation.governance.system_registry.api import system_catalog
class LeafPublicEntryPointTests(unittest.TestCase):
 def test_all_retained_leaves_use_package_level_entrypoints_and_attested_results(self):
  count=0
  for d in system_catalog():
   p=ROOT.joinpath(*d.package_prefix.split('.')); b=p/'api'/'boundary.py'
   if not b.is_file() or 'SystemLeafContract' not in b.read_text(): continue
   count+=1
   provider=__import__(d.package_prefix+'.providers',fromlist=['bind'])
   composition=__import__(d.package_prefix+'.composition',fromlist=['compose'])
   runtime=composition.compose(lambda op,payload:{'ok':True,'node':d.identity.key})
   result=runtime.execute('health.check',{})
   self.assertTrue(result.handler_bound); self.assertEqual(len(result.contract_digest),64); self.assertEqual(len(result.output_digest),64)
   self.assertTrue(provider.provider().describe()['contract_digest'])
  # Exact leaf count is governed by the architecture budget, not frozen by this conformance test.
  self.assertGreater(count,0)
if __name__=='__main__': unittest.main()

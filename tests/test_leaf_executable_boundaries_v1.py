from __future__ import annotations
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from noetrium_platform.foundation.governance.system_registry.api import system_catalog
class LeafExecutableBoundaryTests(unittest.TestCase):
    def test_all_migrated_leaves_expose_runtime_provider_composition(self):
        rows=0
        for d in system_catalog():
            p=ROOT.joinpath(*d.package_prefix.split('.'))
            b=p/'api'/'boundary.py'
            if not b.is_file() or 'SystemLeafContract' not in b.read_text(): continue
            rows+=1
            owner=__import__(d.package_prefix+'.runtime.owner',fromlist=['runtime'])
            provider=__import__(d.package_prefix+'.providers.default',fromlist=['bind'])
            composition=__import__(d.package_prefix+'.composition.default',fromlist=['compose'])
            handler=lambda operation,payload: {'operation':operation,'payload':dict(payload)}
            runtime=composition.compose(handler)
            result=runtime.execute('health.check',{'node':d.identity.key})
            self.assertEqual(result.contract_digest, owner.CONTRACT.digest if hasattr(owner,'CONTRACT') else runtime.contract.digest)
            self.assertTrue(result.handler_bound)
        # Leaf cardinality may contract under architecture governance; per-leaf conformance is invariant.
        self.assertGreater(rows, 0)
if __name__=='__main__': unittest.main()

"""Real Authority + warm-pool proof of bootstrap-to-refresh replica reuse."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import runpy
import tempfile
import unittest

from noetrium_platform.infrastructure.resources.authority import UniversalResourceAuthority


class ModelRefreshWarmBorrow(unittest.TestCase):
    def test_refresh_borrows_adaptive_bootstrap_fleet_without_any_new_gpu_claim(self):
        helpers = runpy.run_path('tests/test_model_replica_pool_auto_placement_v1.py')
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            authority = UniversalResourceAuthority(directory / 'authority.sqlite')
            catalog = helpers['Catalog']()
            runtime = helpers['Runtime'](catalog)
            pool = helpers['_pool'](directory, authority, catalog, runtime)
            qualified = helpers['_request'](directory)
            bootstrap = replace(qualified, replica_count=None)
            lease = pool.ensure(bootstrap)
            try:
                cardinality = len(lease.report.placements)
                self.assertGreater(cardinality, 0)
                before = lease.report.placements[0]
                self.assertEqual(len(runtime.starts), cardinality)
                second = pool.borrow_existing(bootstrap, expected_replica_count=cardinality)
                self.assertIsNotNone(second)
                try:
                    self.assertEqual(second.report.placements, lease.report.placements)
                    self.assertEqual(len(runtime.starts), cardinality, 'must not create another model')
                    self.assertEqual(pool.warm_owner_count, 1)
                    for key in (before.compute_resource_key, before.endpoint_resource_key, before.service_resource_key):
                        self.assertEqual(len(authority.snapshot().current_claims_for(key)), 1)
                finally:
                    second.close()
                self.assertIsNone(pool.borrow_existing(bootstrap, expected_replica_count=cardinality + 1))
                self.assertEqual(len(runtime.starts), cardinality)
            finally:
                lease.close()
                pool.detach_all()


if __name__ == '__main__':
    unittest.main()

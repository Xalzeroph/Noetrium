"""Qualified refresh must reuse exact bootstrap GPU realization, not duplicate it."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from test_model_replica_pool_auto_placement_v1 import Catalog, Runtime, _pool, _request
from noetrium_platform.infrastructure.resources.authority import UniversalResourceAuthority


class ModelReplicaAutoRefreshReuseTests(unittest.TestCase):
    def test_exact_cardinality_adopts_bootstrap_automatic_owner_without_new_gpu(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            authority = UniversalResourceAuthority(root / 'authority.sqlite')
            catalog = Catalog()
            physical = Runtime(catalog)
            pool = _pool(root, authority, catalog, physical)
            bootstrap = replace(_request(root), replica_count=None)
            first = pool.ensure(bootstrap)
            initial = first.report.placements
            self.assertGreaterEqual(len(initial), 1)
            self.assertEqual(len(physical.starts), len(initial))
            refresh = replace(bootstrap, replica_count=len(initial))
            second = pool.borrow_existing(
                replace(refresh, replica_count=None),
                expected_replica_count=len(initial),
            )
            self.assertIsNotNone(second)
            self.assertEqual(second.report.report_digest, first.report.report_digest)
            self.assertEqual(pool.warm_owner_count, 1)
            self.assertEqual(len(physical.starts), len(initial))
            second.close()
            first.close()
            pool.close_all()

    def test_different_replica_count_is_not_aliased(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            authority = UniversalResourceAuthority(root / 'authority.sqlite')
            catalog = Catalog()
            physical = Runtime(catalog)
            pool = _pool(root, authority, catalog, physical)
            bootstrap = replace(_request(root), replica_count=None)
            first = pool.ensure(bootstrap)
            first_count = len(first.report.placements)
            incompatible = replace(bootstrap, replica_count=first_count + 1)
            self.assertIsNone(pool.borrow_existing(
                bootstrap, expected_replica_count=incompatible.replica_count,
            ))
            first.close()
            pool.close_all()


if __name__ == '__main__':
    unittest.main()

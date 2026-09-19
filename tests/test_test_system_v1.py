from __future__ import annotations

import unittest

from scripts.test_system import CATALOG_PATH, ROOT, check, classify, inventory, load_catalog


class TestSystemV1Tests(unittest.TestCase):
    def test_catalog_is_valid_and_covers_every_top_level_test_file(self) -> None:
        rows = check()
        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual({row.path for row in rows}, {path.relative_to(ROOT).as_posix() for path in (ROOT / "tests").glob("test_*.py")})

    def test_hierarchy_has_explicit_release_and_live_boundaries(self) -> None:
        catalog = load_catalog(CATALOG_PATH)
        self.assertEqual(catalog["gates"]["release"]["families"][-1], "release-deployment")
        self.assertEqual(catalog["gates"]["live"]["families"], ["live-qualified"])
        self.assertEqual(catalog["families"]["live-qualified"]["level"], "L8")

    def test_inventory_rows_have_intent_and_risk(self) -> None:
        rows = inventory()
        self.assertTrue(all(row.intent and row.risk and row.gates for row in rows))

    def test_public_checkpoint_composition_is_durability_recovery(self) -> None:
        catalog = load_catalog(CATALOG_PATH)
        row = classify(ROOT / "tests" / "test_public_checkpoint_composition_v1.py", catalog)
        self.assertEqual(row.rule_id, "durability")
        self.assertEqual(row.family, "durability-recovery")
        self.assertEqual(row.level, "L4")


    def test_section42_checkpoint_and_trial_identity_tests_keep_exact_taxonomy(self) -> None:
        catalog = load_catalog(CATALOG_PATH)
        checkpoint = classify(ROOT / "tests" / "test_research_checkpoint_participant_v1.py", catalog)
        self.assertEqual(checkpoint.rule_id, "durability")
        self.assertEqual(checkpoint.family, "durability-recovery")
        self.assertEqual(checkpoint.level, "L4")
        for name in (
            "test_trial_identity_freeze_v115.py",
            "test_trial_protocol_identity_v1.py",
            "test_section42_identity_facets_v1.py",
        ):
            row = classify(ROOT / "tests" / name, catalog)
            self.assertEqual(row.rule_id, "contracts")
            self.assertEqual(row.family, "typed-contracts")
            self.assertEqual(row.level, "L1")

    def test_section42_producer_tests_have_exact_scientific_classification(self) -> None:
        catalog = load_catalog(CATALOG_PATH)
        for name in (
            "test_measurement_protocol_v1.py",
            "test_research_compiler_v1.py",
            "test_trial_matrix_executor_v1.py",
        ):
            row = classify(ROOT / "tests" / name, catalog)
            self.assertEqual(row.rule_id, "section42-scientific")
            self.assertEqual(row.family, "scientific-domain")
            self.assertEqual(row.level, "L6")

    def test_resource_shared_carrier_fencing_is_l5_concurrency(self) -> None:
        catalog = load_catalog(CATALOG_PATH)
        row = classify(
            ROOT / "tests" / "test_resource_shared_carrier_fencing_v1.py",
            catalog,
        )
        self.assertEqual(row.rule_id, "concurrency")
        self.assertEqual(row.family, "concurrency-capacity")
        self.assertEqual(row.level, "L5")

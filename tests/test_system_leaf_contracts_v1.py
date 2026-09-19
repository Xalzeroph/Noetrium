from __future__ import annotations

from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from noetrium_platform.foundation.governance.system_registry.api import system_catalog
from noetrium_platform.foundation.kernel.kernel.leaf_contract import LeafExecutionError


class SystemLeafContractTests(unittest.TestCase):
    def test_migrated_declaration_leaves_have_contract_and_runtime_owner(self) -> None:
        migrated = 0
        catalog = json.loads(
            (ROOT / "noetrium_platform/foundation/governance/system_registry/catalog.json")
            .read_text(encoding="utf-8")
        )
        for descriptor in system_catalog():
            package = ROOT.joinpath(*descriptor.package_prefix.split("."))
            boundary = package / "api" / "boundary.py"
            if not boundary.is_file() or "SystemLeafContract" not in boundary.read_text(encoding="utf-8"):
                continue
            migrated += 1
            boundary_module = __import__(descriptor.package_prefix + ".api.boundary", fromlist=["contract"])
            owner_module = __import__(descriptor.package_prefix + ".runtime.owner", fromlist=["owner"])
            contract = boundary_module.contract()
            owner = owner_module.owner()
            self.assertIs(boundary_module.CONTRACT, contract)
            self.assertIs(owner_module.OWNER, owner)
            self.assertEqual(contract.node, descriptor.identity.key)
            # Legacy leaf contracts are declaration metadata; only node_kind=authority
            # materializes a direct registry AuthorityDescriptor in vNext.
            self.assertEqual(contract.authority_id, catalog[descriptor.identity.key]["authority"])
            self.assertEqual(owner.owner_id, contract.authority_id)
            if descriptor.node_kind.value == "authority":
                self.assertEqual(contract.authority_id, descriptor.authority_id)
            else:
                self.assertIsNone(descriptor.authority_id)
            self.assertEqual(contract.package_prefix, descriptor.package_prefix)
            self.assertEqual(len(contract.digest), 64)
            self.assertEqual(contract.api_module, descriptor.package_prefix + ".api")
            self.assertEqual(contract.runtime_module, descriptor.package_prefix + ".runtime")
            self.assertTrue((package / "api").is_dir())
            self.assertTrue((package / "runtime").is_dir())
            self.assertTrue((package / "providers").is_dir())
            self.assertTrue((package / "composition").is_dir())
        # Architecture convergence may delete generic shells; retained leaves must all conform.
        self.assertGreater(migrated, 0)

    def test_generic_leaf_runtime_cannot_create_an_independent_state_authority(self) -> None:
        descriptor = next(
            row for row in system_catalog()
            if row.node_kind.value != "authority"
            and row.package_prefix.startswith("noetrium_platform.")
            and (ROOT.joinpath(*row.package_prefix.split(".")) / "runtime" / "owner.py").is_file()
        )
        owner_module = __import__(descriptor.package_prefix + ".runtime.owner", fromlist=["owner"])
        owner = owner_module.owner()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                LeafExecutionError,
                "generic leaf-local state is forbidden",
            ):
                owner.bind(lambda _operation, _payload: None, Path(directory) / "state.json")


if __name__ == "__main__":
    unittest.main()

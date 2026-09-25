from __future__ import annotations

import argparse
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from generate_authority_disposition_matrix import generate as generate_authority_disposition_matrix
from generate_downstream_contracts import generate
from generate_interface_schemas import generate as generate_interface_schemas
from sync_leaf_contract_metadata import sync_leaf_contract_metadata
from sync_registered_system_shapes import sync_registered_system_shapes
from audit_registered_system_surfaces import audit as audit_registered_system_surfaces
from readme_i18n import load_languages, mark_current, sync_navigation
from check_readme_i18n import validate_root
from noetrium_platform.foundation.governance.architecture.capability_index import (
    build_capability_index,
)
from noetrium_platform.foundation.kernel.kernel.canonical import canonical_bytes

_CAPABILITY_INDEX = Path("docs/architecture/CAPABILITY_INDEX.json")


def _sync_capability_index(root: Path, *, check: bool) -> bool:
    path = root / _CAPABILITY_INDEX
    expected = canonical_bytes(build_capability_index(root))
    current = path.read_bytes() if path.is_file() else None
    if check:
        if current != expected:
            print(
                "generated capability index drift: "
                f"{_CAPABILITY_INDEX.as_posix()}",
                file=sys.stderr,
            )
            return False
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    if current != expected:
        path.write_bytes(expected)
    return True


def update(root: Path) -> int:
    findings = sync_registered_system_shapes(root, check=False)
    if findings:
        for finding in findings:
            print(f"registered system shape sync failed: {finding}")
        return 1
    leaf_findings = sync_leaf_contract_metadata(root, check=False)
    if leaf_findings:
        for finding in leaf_findings:
            print(f"leaf contract metadata sync failed: {finding}")
        return 1
    if not _sync_capability_index(root, check=False):
        return 1
    if generate_authority_disposition_matrix(root, check=False) != 0:
        return 1
    result = generate(root, check=False)
    if result != 0:
        return result
    result = generate_interface_schemas(root, check=False)
    if result != 0:
        return result
    surface_findings = tuple(
        finding
        for row in audit_registered_system_surfaces(root)
        for finding in row.findings
    )
    if surface_findings:
        print("registered system surface audit failed")
        for finding in surface_findings:
            print(f"- {finding.code}: {finding.system_key}: {finding.detail}")
        return 1
    sync_navigation(root)
    locales = tuple(row["locale"] for row in load_languages(root)["languages"])
    mark_current(locales, root)
    return 0


def check(root: Path) -> int:
    shape_findings = sync_registered_system_shapes(root, check=True)
    if shape_findings:
        print("registered system shape check failed")
        for finding in shape_findings:
            print(f"- {finding}")
        return 1
    leaf_findings = sync_leaf_contract_metadata(root, check=True)
    if leaf_findings:
        print("leaf contract metadata check failed")
        for finding in leaf_findings:
            print(f"- {finding}")
        return 1
    if not _sync_capability_index(root, check=True):
        return 1
    if generate_authority_disposition_matrix(root, check=True) != 0:
        return 1
    if generate(root, check=True) != 0:
        return 1
    if generate_interface_schemas(root, check=True) != 0:
        return 1
    surface_findings = tuple(
        finding
        for row in audit_registered_system_surfaces(root)
        for finding in row.findings
    )
    if surface_findings:
        print("registered system surface audit failed")
        for finding in surface_findings:
            print(f"- {finding.code}: {finding.system_key}: {finding.detail}")
        return 1
    errors = validate_root(root)
    if errors:
        print("generated documentation check failed")
        for error in errors:
            print(f"- {error}")
        return 1
    print("GENERATED_DOCUMENTATION_CHECK_PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate Noetrium authority metadata, leaf declarations, public facades, catalogs, README blocks, and freshness state."
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    return check(root) if args.check else update(root)


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "noetrium_platform/foundation/governance/system_registry/catalog.json"

_CONTRACT_FIELDS = (
    "system_id",
    "node",
    "package_prefix",
    "authority_id",
    "owns",
    "must_not_own",
    "api_module",
    "runtime_module",
    "provider_module",
    "composition_module",
)

_CONSTANT_FIELDS = {
    "SYSTEM": "system_id",
    "NODE": "node",
    "OWNS": "owns",
    "MUST_NOT_OWN": "must_not_own",
    "AUTHORITY": "authority_id",
}


def _catalog(root: Path) -> dict[str, dict[str, object]]:
    path = root / CATALOG.relative_to(ROOT)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not value:
        raise RuntimeError("canonical system registry must be a non-empty object")
    result: dict[str, dict[str, object]] = {}
    for key, raw in value.items():
        if not isinstance(key, str) or not isinstance(raw, dict):
            raise RuntimeError("canonical system registry entries must be objects")
        result[key] = raw
    return result


def _expected(system_key: str, descriptor: dict[str, object]) -> dict[str, str]:
    package = descriptor.get("package_prefix")
    authority = descriptor.get("authority")
    owns = descriptor.get("owns")
    must_not_own = descriptor.get("must_not_own")
    if not all(isinstance(value, str) and value.strip() for value in (package, authority, owns, must_not_own)):
        raise RuntimeError(f"invalid leaf-contract metadata in catalog for {system_key!r}")
    package = str(package)
    return {
        "system_id": system_key.split("/", 1)[0],
        "node": system_key,
        "package_prefix": package,
        "authority_id": str(authority),
        "owns": str(owns),
        "must_not_own": str(must_not_own),
        "api_module": package + ".api",
        "runtime_module": package + ".runtime",
        "provider_module": package + ".providers",
        "composition_module": package + ".composition",
    }


def _literal_edits(source: str, expected: dict[str, str]) -> list[tuple[int, int, str]]:
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    starts: list[int] = []
    position = 0
    for line in lines:
        starts.append(position)
        position += len(line)

    def span(node: ast.AST) -> tuple[int, int]:
        if not hasattr(node, "lineno") or not hasattr(node, "end_lineno"):
            raise RuntimeError("Python AST does not expose source positions")
        start = starts[node.lineno - 1] + node.col_offset
        end = starts[node.end_lineno - 1] + node.end_col_offset
        return start, end

    edits: list[tuple[int, int, str]] = []
    contract_seen = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            field = _CONSTANT_FIELDS.get(node.targets[0].id)
            if field is not None and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                replacement = repr(expected[field])
                if node.value.value != expected[field]:
                    start, end = span(node.value)
                    edits.append((start, end, replacement))
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "SystemLeafContract":
            continue
        if contract_seen:
            raise RuntimeError("multiple SystemLeafContract declarations in one boundary")
        contract_seen = True
        keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
        missing = [field for field in _CONTRACT_FIELDS if field not in keywords]
        if missing:
            raise RuntimeError("SystemLeafContract is missing fields: " + ", ".join(missing))
        for field in _CONTRACT_FIELDS:
            value = keywords[field]
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                raise RuntimeError(f"SystemLeafContract field {field!r} must remain a literal string")
            if value.value == expected[field]:
                continue
            start, end = span(value)
            edits.append((start, end, repr(expected[field])))
    if not contract_seen:
        return []
    return edits


def _apply_edits(source: str, edits: list[tuple[int, int, str]]) -> str:
    result = source
    for start, end, replacement in sorted(edits, reverse=True):
        result = result[:start] + replacement + result[end:]
    return result


def sync_leaf_contract_metadata(root: Path, *, check: bool = False) -> tuple[str, ...]:
    """Synchronize metadata only for leaf contracts that already exist.

    The canonical registry owns topology/ownership semantics.  This function does
    not synthesize new SystemLeafContract declarations; it only keeps existing
    literal declarations and their companion declarative constants aligned with
    that source of truth.
    """

    root = Path(root).resolve()
    findings: list[str] = []
    for system_key, descriptor in _catalog(root).items():
        package = descriptor.get("package_prefix")
        if not isinstance(package, str) or not package.strip():
            raise RuntimeError(f"invalid package_prefix for {system_key!r}")
        boundary = root.joinpath(*package.split("."), "api", "boundary.py")
        if not boundary.is_file():
            continue
        source = boundary.read_text(encoding="utf-8")
        expected = _expected(system_key, descriptor)
        edits = _literal_edits(source, expected)
        if not edits:
            continue
        relative = str(boundary.relative_to(root))
        if check:
            findings.append(f"leaf contract metadata drift: {system_key}: {relative}")
            continue
        boundary.write_text(_apply_edits(source, edits), encoding="utf-8")
    return tuple(findings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synchronize existing literal SystemLeafContract metadata from the canonical registry.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    findings = sync_leaf_contract_metadata(args.root, check=args.check)
    for finding in findings:
        print(finding, file=sys.stderr)
    print(json.dumps({"schema": "leaf-contract-metadata-sync.v1", "clean": not findings, "finding_count": len(findings)}, sort_keys=True))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())

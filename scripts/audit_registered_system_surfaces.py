from __future__ import annotations

import argparse
import ast
import importlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_downstream_contracts import build_surfaces, _public_symbols


@dataclass(frozen=True, slots=True)
class SurfaceFinding:
    code: str
    system_key: str
    source: str
    detail: str


@dataclass(frozen=True, slots=True)
class SystemSurfaceAudit:
    system_key: str
    package_prefix: str
    provides: tuple[str, ...]
    children: tuple[str, ...]
    api_modules: int
    api_symbols: int
    facade_module: str
    findings: tuple[SurfaceFinding, ...]


def _registry(root: Path) -> dict[str, dict[str, object]]:
    path = root / "noetrium_platform/foundation/governance/system_registry/catalog.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not value:
        raise RuntimeError("canonical system registry must be a non-empty object")
    return value


def _runtime_export_drift(module_name: str, expected: tuple[str, ...]) -> tuple[str, ...]:
    module = importlib.import_module(module_name)
    declared = getattr(module, "__all__", None)
    if declared is None:
        return ()
    observed = tuple(declared)
    if len(observed) != len(set(observed)):
        return ("runtime __all__ contains duplicate symbols",)
    missing = sorted(set(observed) - set(expected))
    extra = sorted(set(expected) - set(observed))
    rows = []
    if missing:
        rows.append("generator misses runtime exports: " + ", ".join(missing))
    if extra:
        rows.append("generator exposes symbols absent from runtime __all__: " + ", ".join(extra))
    return tuple(rows)


def _module_name(root: Path, path: Path) -> str:
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _uncovered_public_api_findings(
    root: Path,
    *,
    covered_sources: frozenset[str],
    covered_object_ids: frozenset[int],
) -> tuple[SurfaceFinding, ...]:
    """Reject public API symbols that are neither registered nor a pure alias of one.

    Compatibility facades such as ``noetrium_platform.api`` are allowed only when
    every exported object is already present in a registered generated system surface.
    """

    rows: list[SurfaceFinding] = []
    metadata_only_prefixes = tuple(
        str(descriptor["package_prefix"]).replace(".", "/")
        for descriptor in _registry(root).values()
        if descriptor.get("downstream_surface") == "metadata_only"
    )
    for base in (root / "noetrium_platform", root / "components", root / "orchestration"):
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            parts = path.relative_to(base).parts
            if not (path.name == "api.py" or "api" in parts[:-1]):
                continue
            if path.name.startswith("_") and path.name != "__init__.py":
                continue
            if any(relative == prefix or relative.startswith(prefix + "/") for prefix in metadata_only_prefixes):
                continue
            try:
                symbols = _public_symbols(path)
            except BaseException as exc:
                rows.append(SurfaceFinding(
                    "PUBLIC_API_STATIC_EVALUATION_FAILED",
                    "unregistered_api", relative, f"{type(exc).__name__}: {exc}",
                ))
                continue
            if not symbols or relative in covered_sources:
                continue
            module_name = _module_name(root, path)
            try:
                module = importlib.import_module(module_name)
            except BaseException as exc:
                rows.append(SurfaceFinding(
                    "UNCOVERED_PUBLIC_API_IMPORT_FAILED",
                    "unregistered_api", relative, f"{type(exc).__name__}: {exc}",
                ))
                continue
            missing = tuple(
                name for name in symbols
                if id(getattr(module, name)) not in covered_object_ids
            )
            if missing:
                rows.append(SurfaceFinding(
                    "UNREGISTERED_PUBLIC_API_EXPORT",
                    "unregistered_api", relative, ", ".join(missing),
                ))
    return tuple(rows)


def _convenience_contract_findings(root: Path) -> tuple[SurfaceFinding, ...]:
    rows: list[SurfaceFinding] = []
    for path in sorted((root / "noetrium/contracts").glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            rows.append(SurfaceFinding("CONVENIENCE_PARSE_FAILED", "contracts", str(path.relative_to(root)), str(exc)))
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            module = node.module
            if not module.startswith("noetrium_platform."):
                continue
            parts = module.split(".")
            if any(segment in {"runtime", "providers", "composition"} for segment in parts):
                rows.append(SurfaceFinding(
                    "CONVENIENCE_IMPORTS_PRIVATE_IMPLEMENTATION",
                    "contracts",
                    str(path.relative_to(root)),
                    f"line {getattr(node, 'lineno', 0)} imports {module}",
                ))
    return tuple(rows)


def audit(root: Path) -> tuple[SystemSurfaceAudit, ...]:
    root = root.resolve()
    registry = _registry(root)
    children: dict[str, list[str]] = {key: [] for key in registry}
    for key, descriptor in registry.items():
        parent = descriptor.get("parent")
        if isinstance(parent, str):
            parent = parent.replace(".", "/")
            children.setdefault(parent, []).append(key)
    surfaces = {surface.system_key: surface for surface in build_surfaces(root)}
    covered_sources = frozenset(
        module.source for surface in surfaces.values() for module in surface.api_modules
    )
    covered_object_ids: set[int] = set()
    for surface in surfaces.values():
        for module in surface.api_modules:
            imported = importlib.import_module(module.module)
            covered_object_ids.update(id(getattr(imported, name)) for name in module.symbols)
    rows: list[SystemSurfaceAudit] = []
    for key, descriptor in registry.items():
        surface = surfaces.get(key)
        findings: list[SurfaceFinding] = []
        if surface is None:
            findings.append(SurfaceFinding("REGISTERED_SURFACE_MISSING", key, str(descriptor.get("package_prefix", "")), "generator returned no surface"))
            rows.append(SystemSurfaceAudit(key, str(descriptor.get("package_prefix", "")), tuple(descriptor.get("provides", ())), tuple(sorted(children.get(key, ()))), 0, 0, "", tuple(findings)))
            continue
        symbol_count = sum(len(module.symbols) for module in surface.api_modules)
        for module in surface.api_modules:
            try:
                drift = _runtime_export_drift(module.module, module.symbols)
            except BaseException as exc:
                findings.append(SurfaceFinding("PUBLIC_API_IMPORT_FAILED", key, module.source, f"{type(exc).__name__}: {exc}"))
                continue
            findings.extend(SurfaceFinding("PUBLIC_API_EXPORT_DRIFT", key, module.source, detail) for detail in drift)
        facade_path = root.joinpath(*surface.facade_module.split(".")).with_suffix(".py")
        if facade_path.is_file():
            try:
                facade = importlib.import_module(surface.facade_module)
                if getattr(facade, "SYSTEM_KEY", None) != key:
                    findings.append(SurfaceFinding("GENERATED_FACADE_IDENTITY_DRIFT", key, str(facade_path.relative_to(root)), "SYSTEM_KEY mismatch"))
            except BaseException as exc:
                findings.append(SurfaceFinding("GENERATED_FACADE_IMPORT_FAILED", key, str(facade_path.relative_to(root)), f"{type(exc).__name__}: {exc}"))
        provides = tuple(descriptor.get("provides", ()))
        system_children = tuple(sorted(children.get(key, ())))
        downstream_surface = str(descriptor.get("downstream_surface", "public"))
        if downstream_surface not in {"public", "metadata_only"}:
            findings.append(SurfaceFinding(
                "INVALID_DOWNSTREAM_SURFACE_MODE", key,
                str(descriptor.get("package_prefix", "")), downstream_surface,
            ))
        if downstream_surface == "metadata_only":
            if system_children:
                findings.append(SurfaceFinding(
                    "METADATA_ONLY_SYSTEM_HAS_CHILDREN", key,
                    str(descriptor.get("package_prefix", "")),
                    "metadata-only is reserved for leaf implementation/product routing nodes",
                ))
            if symbol_count:
                findings.append(SurfaceFinding(
                    "METADATA_ONLY_SYSTEM_EXPORTS_API", key,
                    str(descriptor.get("package_prefix", "")),
                    f"metadata-only system exports {symbol_count} public symbols",
                ))
            if provides:
                findings.append(SurfaceFinding(
                    "METADATA_ONLY_SYSTEM_PROVIDES_CAPABILITY", key,
                    str(descriptor.get("package_prefix", "")),
                    ", ".join(provides),
                ))
        elif not system_children and symbol_count == 0:
            findings.append(SurfaceFinding(
                "PUBLIC_LEAF_WITHOUT_PUBLIC_API", key,
                str(descriptor.get("package_prefix", "")),
                "public leaf system exposes no generated API symbols",
            ))
        rows.append(SystemSurfaceAudit(
            system_key=key,
            package_prefix=surface.package_prefix,
            provides=provides,
            children=system_children,
            api_modules=len(surface.api_modules),
            api_symbols=symbol_count,
            facade_module=surface.facade_module,
            findings=tuple(findings),
        ))
    convenience = _convenience_contract_findings(root)
    if convenience:
        rows.append(SystemSurfaceAudit("contracts", "noetrium.contracts", (), (), 0, 0, "", convenience))
    uncovered = _uncovered_public_api_findings(
        root,
        covered_sources=covered_sources,
        covered_object_ids=frozenset(covered_object_ids),
    )
    if uncovered:
        rows.append(SystemSurfaceAudit("unregistered_api", "", (), (), 0, 0, "", uncovered))
    return tuple(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    rows = audit(args.root)
    findings = tuple(item for row in rows for item in row.findings)
    document = {
        "schema": "registered-system-surface-audit.v1",
        "system_count": sum(row.system_key != "contracts" for row in rows),
        "finding_count": len(findings),
        "systems": [asdict(row) for row in rows if row.system_key != "contracts"],
        "findings": [asdict(item) for item in findings],
    }
    text = json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(json.dumps({"schema": document["schema"], "system_count": document["system_count"], "finding_count": document["finding_count"]}, sort_keys=True))
    for finding in findings:
        print(f"{finding.code}: {finding.system_key}: {finding.source}: {finding.detail}", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())

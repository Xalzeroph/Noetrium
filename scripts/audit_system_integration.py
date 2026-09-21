#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "noetrium_platform/foundation/governance/system_registry/catalog.json"
DOWNSTREAM = ROOT / "noetrium/contracts/downstream_capability_catalog.json"


@dataclass(frozen=True)
class SystemIntegrationRow:
    system_key: str
    package_prefix: str
    downstream_surface: str
    node_kind: str
    declared_shape: tuple[str, ...]
    present_shape: tuple[str, ...]
    missing_shape: tuple[str, ...]
    python_file_count: int
    production_consumers: tuple[str, ...]
    production_composition_consumers: tuple[str, ...]
    research_consumers: tuple[str, ...]
    script_consumers: tuple[str, ...]
    test_consumers: tuple[str, ...]
    direct_runtime_or_provider_consumers: tuple[str, ...]
    facade_module: str | None
    status: str


def module_for_path(path: Path) -> str | None:
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return None
    if rel.suffix != ".py":
        return None
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def imports_for_path(path: Path) -> tuple[str, ...]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return ()
    result: list[str] = []
    source_module = module_for_path(path) or ""
    source_parts = source_module.split(".")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = source_parts if path.name == "__init__.py" else source_parts[:-1]
                keep = max(0, len(base) - node.level + 1)
                prefix = base[:keep]
                if node.module:
                    prefix.extend(node.module.split("."))
                module = ".".join(prefix)
            else:
                module = node.module or ""
            if module:
                result.append(module)
    return tuple(result)


def owner_for_module(module: str, owners: tuple[tuple[str, str], ...]) -> str | None:
    for prefix, key in owners:
        if module == prefix or module.startswith(prefix + "."):
            return key
    return None


def channel_for_path(path: Path) -> str:
    first = path.relative_to(ROOT).parts[0]
    return {
        "noetrium_platform": "production",
        "research": "research",
        "scripts": "script",
        "tests": "test",
    }.get(first, "other")


def build_report() -> dict:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    downstream_document = json.loads(DOWNSTREAM.read_text(encoding="utf-8"))
    downstream = downstream_document.get("systems", downstream_document)
    if not isinstance(downstream, list):
        raise TypeError("downstream capability catalog systems must be a list")
    downstream_by_key = {
        row["system_key"]: row
        for row in downstream
        if isinstance(row, dict) and isinstance(row.get("system_key"), str)
    }
    owners = tuple(
        sorted(
            ((str(spec["package_prefix"]), str(key)) for key, spec in catalog.items()),
            key=lambda row: len(row[0]),
            reverse=True,
        )
    )

    inbound: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    composition_inbound: dict[str, set[str]] = defaultdict(set)
    direct_concrete: dict[str, set[str]] = defaultdict(set)

    for scan_root in (
        ROOT / "noetrium_platform",
        ROOT / "research",
        ROOT / "scripts",
        ROOT / "tests",
    ):
        for path in scan_root.rglob("*.py"):
            module = module_for_path(path)
            if not module:
                continue
            source_owner = owner_for_module(module, owners)
            channel = channel_for_path(path)
            for imported in imports_for_path(path):
                target_owner = owner_for_module(imported, owners)
                if target_owner is None or target_owner == source_owner:
                    continue
                inbound[target_owner][channel].add(module)
                if channel == "production" and ".composition" in imported:
                    composition_inbound[target_owner].add(module)
                if channel == "production" and (
                    ".runtime" in imported or ".providers" in imported
                ):
                    direct_concrete[target_owner].add(module)

    rows: list[SystemIntegrationRow] = []
    for key, spec in sorted(catalog.items()):
        package = str(spec["package_prefix"])
        package_path = ROOT / Path(*package.split("."))
        declared = tuple(str(v) for v in spec.get("shape", ()))
        present = tuple(
            shape
            for shape in declared
            if (package_path / shape).is_dir()
            or (package_path / shape).with_suffix(".py").is_file()
        )
        missing = tuple(shape for shape in declared if shape not in present)
        python_files = tuple(package_path.rglob("*.py")) if package_path.exists() else ()
        production = tuple(sorted(inbound[key]["production"]))
        prod_composition = tuple(sorted(composition_inbound[key]))
        research = tuple(sorted(inbound[key]["research"]))
        scripts = tuple(sorted(inbound[key]["script"]))
        tests = tuple(sorted(inbound[key]["test"]))
        concrete = tuple(sorted(direct_concrete[key]))
        facade = downstream_by_key.get(key, {}).get("facade_module")

        if missing:
            status = "declared-shape-missing"
        elif spec.get("downstream_surface") == "public" and not facade:
            status = "public-facade-missing"
        elif production:
            status = "production-integrated"
        elif scripts or research:
            status = "operations-or-research-only"
        elif tests:
            status = "test-only"
        elif python_files:
            status = "implemented-unconsumed"
        else:
            status = "catalog-only"

        rows.append(SystemIntegrationRow(
            system_key=key,
            package_prefix=package,
            downstream_surface=str(spec.get("downstream_surface", "")),
            node_kind=str(spec.get("node_kind", "")),
            declared_shape=declared,
            present_shape=present,
            missing_shape=missing,
            python_file_count=len(python_files),
            production_consumers=production,
            production_composition_consumers=prod_composition,
            research_consumers=research,
            script_consumers=scripts,
            test_consumers=tests,
            direct_runtime_or_provider_consumers=concrete,
            facade_module=str(facade) if facade else None,
            status=status,
        ))

    status_counts = Counter(row.status for row in rows)
    disconnected_statuses = {
        "operations-or-research-only",
        "test-only",
        "implemented-unconsumed",
        "declared-shape-missing",
        "public-facade-missing",
    }
    return {
        "schema": "noetrium.system-integration-audit.v1",
        "system_count": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "disconnected_system_count": sum(
            row.status in disconnected_statuses for row in rows
        ),
        "direct_concrete_dependency_system_count": sum(
            bool(row.direct_runtime_or_provider_consumers) for row in rows
        ),
        "systems": [asdict(row) for row in rows],
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Noetrium system integration audit",
        "",
        f"- Registered systems: {report['system_count']}",
        f"- Disconnected/non-production-consumed: {report['disconnected_system_count']}",
        f"- Cross-system direct runtime/provider pressure: {report['direct_concrete_dependency_system_count']}",
        "",
        "## Status counts",
        "",
    ]
    for key, value in report["status_counts"].items():
        lines.append(f"- {key}: {value}")
    lines += [
        "",
        "## Systems needing wiring attention",
        "",
        "| System | Status | Prod | Ops/research | Tests | Composition consumers |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in report["systems"]:
        if row["status"] == "production-integrated":
            continue
        lines.append(
            "| {key} | {status} | {prod} | {ops} | {tests} | {comp} |".format(
                key=row["system_key"],
                status=row["status"],
                prod=len(row["production_consumers"]),
                ops=len(row["script_consumers"]) + len(row["research_consumers"]),
                tests=len(row["test_consumers"]),
                comp=len(row["production_composition_consumers"]),
            )
        )
    lines += [
        "",
        "## Cross-system concrete-boundary pressure",
        "",
        "These systems are imported through runtime/providers by another production system.",
        "They require review because the preferred cross-system seam is API plus composition.",
        "",
    ]
    for row in report["systems"]:
        if row["direct_runtime_or_provider_consumers"]:
            lines.append(
                "- {key}: {values}".format(
                    key=row["system_key"],
                    values=", ".join(row["direct_runtime_or_provider_consumers"]),
                )
            )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--fail-on-shape", action="store_true")
    args = parser.parse_args(argv)
    report = build_report()
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(report))
    print(json.dumps({
        "system_count": report["system_count"],
        "status_counts": report["status_counts"],
        "disconnected_system_count": report["disconnected_system_count"],
        "direct_concrete_dependency_system_count": report["direct_concrete_dependency_system_count"],
    }, indent=2, sort_keys=True))
    if args.fail_on_shape and (
        report["status_counts"].get("declared-shape-missing", 0)
        or report["status_counts"].get("public-facade-missing", 0)
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

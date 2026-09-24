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
COMPONENTS = ROOT / "noetrium_platform/foundation/governance/system_registry/components.json"
DOWNSTREAM = ROOT / "noetrium/contracts/downstream_capability_catalog.json"
SYSTEM_PLANES = frozenset({"api", "runtime", "providers", "composition"})


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


@dataclass(frozen=True)
class LayerIntegrationRow:
    node_key: str
    topology_level: str
    system_key: str
    parent_key: str
    package_prefix: str
    node_kind: str
    declared_shape: tuple[str, ...]
    present_shape: tuple[str, ...]
    missing_shape: tuple[str, ...]
    python_file_count: int
    production_consumers: tuple[str, ...]
    research_consumers: tuple[str, ...]
    script_consumers: tuple[str, ...]
    test_consumers: tuple[str, ...]
    direct_runtime_or_provider_consumers: tuple[str, ...]
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


def leaf_contract_ready(package_path: Path) -> bool:
    boundary = package_path / "api" / "boundary.py"
    owner = package_path / "runtime" / "owner.py"
    composition = package_path / "composition" / "default.py"
    if not all(path.is_file() for path in (boundary, owner, composition)):
        return False
    try:
        boundary_text = boundary.read_text(encoding="utf-8")
        owner_text = owner.read_text(encoding="utf-8")
        composition_text = composition.read_text(encoding="utf-8")
    except OSError:
        return False
    return (
        "SystemLeafContract" in boundary_text
        and "SystemLeafRuntimeOwner" in owner_text
        and "def compose(" in composition_text
    )



def aggregate_shell_ready(package_path: Path, child_keys: tuple[str, ...]) -> bool:
    if not child_keys:
        return False
    allowed = {"__init__.py", "boundary.py"}
    for shape in ("api", "runtime", "providers", "composition"):
        root = package_path / shape
        if not root.is_dir():
            continue
        for path in root.glob("*.py"):
            if path.name not in allowed:
                return False
    return True


def build_report() -> dict:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    components = json.loads(COMPONENTS.read_text(encoding="utf-8"))
    if not isinstance(components, dict):
        raise TypeError("component catalog must be a JSON object")

    component_keys = set(components)
    facet_specs: dict[str, dict[str, object]] = {}
    topology_errors: list[str] = []
    for component_key, component in sorted(components.items()):
        if not isinstance(component, dict):
            topology_errors.append(
                f"component {component_key!r} descriptor is not an object"
            )
            continue
        system_key = component.get("system")
        parent_key = component.get("parent")
        if system_key not in catalog:
            topology_errors.append(
                f"component {component_key!r} references missing system {system_key!r}"
            )
        if parent_key not in catalog and parent_key not in component_keys:
            topology_errors.append(
                f"component {component_key!r} references missing parent {parent_key!r}"
            )
        prefix = component.get("package_prefix")
        if not isinstance(prefix, str) or not prefix.strip():
            topology_errors.append(
                f"component {component_key!r} has invalid package_prefix"
            )
        for facet in component.get("internal_facets", ()):
            if not isinstance(facet, dict):
                topology_errors.append(
                    f"component {component_key!r} has non-object internal facet"
                )
                continue
            facet_key = facet.get("key")
            if not isinstance(facet_key, str) or not facet_key.strip():
                topology_errors.append(
                    f"component {component_key!r} has facet without key"
                )
                continue
            if facet_key in facet_specs or facet_key in component_keys or facet_key in catalog:
                topology_errors.append(
                    f"duplicate topology key for internal facet {facet_key!r}"
                )
                continue
            enriched = dict(facet)
            enriched["system"] = system_key
            enriched["parent"] = component_key
            facet_specs[facet_key] = enriched

    all_dependency_keys = set(catalog) | component_keys | set(facet_specs)
    for component_key, component in sorted(components.items()):
        if not isinstance(component, dict):
            continue
        for dependency in component.get("requires", ()):
            if dependency not in all_dependency_keys:
                topology_errors.append(
                    f"component {component_key!r} requires missing topology node "
                    f"{dependency!r}"
                )

    topology_specs: dict[str, tuple[str, dict[str, object]]] = {}
    for component_key, component in components.items():
        if isinstance(component, dict):
            topology_specs[str(component_key)] = ("component", component)
    for facet_key, facet in facet_specs.items():
        topology_specs[facet_key] = ("internal_facet", facet)

    parent_by_key = {
        key: str(spec.get("parent"))
        for key, (_level, spec) in topology_specs.items()
    }
    for key in topology_specs:
        seen: set[str] = set()
        current = key
        while current in parent_by_key:
            if current in seen:
                topology_errors.append(f"component/facet parent cycle at {key!r}")
                break
            seen.add(current)
            parent = parent_by_key[current]
            if parent in catalog:
                break
            if parent not in topology_specs:
                topology_errors.append(
                    f"topology node {current!r} has unresolved parent {parent!r}"
                )
                break
            current = parent

    for key, (_level, spec) in topology_specs.items():
        prefix = spec.get("package_prefix")
        if not isinstance(prefix, str) or not prefix.strip():
            continue
        package_path = ROOT / Path(*prefix.split("."))
        if not package_path.exists() and not package_path.with_suffix(".py").exists():
            topology_errors.append(
                f"topology node {key!r} package_prefix {prefix!r} does not exist"
            )
        declared_shape = spec.get("shape", ())
        if not isinstance(declared_shape, list):
            topology_errors.append(
                f"topology node {key!r} shape is not a list"
            )
            continue
        unsupported = tuple(
            shape for shape in declared_shape
            if not isinstance(shape, str) or shape not in SYSTEM_PLANES
        )
        if unsupported:
            topology_errors.append(
                f"topology node {key!r} has unsupported shape entries {unsupported!r}"
            )
    children_by_key: dict[str, list[str]] = {str(key): [] for key in catalog}
    for child_key, child_spec in catalog.items():
        parent = child_spec.get("parent")
        if isinstance(parent, str):
            normalized = parent.replace(".", "/")
            children_by_key.setdefault(normalized, []).append(str(child_key))
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
    topology_owners = tuple(
        sorted(
            (
                (str(spec["package_prefix"]), str(key))
                for key, (_level, spec) in topology_specs.items()
                if isinstance(spec.get("package_prefix"), str)
            ),
            key=lambda row: len(row[0]),
            reverse=True,
        )
    )

    inbound: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    composition_inbound: dict[str, set[str]] = defaultdict(set)
    direct_concrete: dict[str, set[str]] = defaultdict(set)
    topology_inbound: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    topology_direct_concrete: dict[str, set[str]] = defaultdict(set)
    dynamic_environment_consumers: set[str] = set()

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
            source_topology_owner = owner_for_module(module, topology_owners)
            channel = channel_for_path(path)
            imported_modules = imports_for_path(path)
            if (
                channel == "production"
                and "noetrium_platform.capabilities.environment.category.composition"
                in imported_modules
            ):
                dynamic_environment_consumers.add(module)
            for imported in imported_modules:
                target_owner = owner_for_module(imported, owners)
                if target_owner is not None and target_owner != source_owner:
                    inbound[target_owner][channel].add(module)
                    if channel == "production" and ".composition" in imported:
                        composition_inbound[target_owner].add(module)
                    if channel == "production" and (
                        ".runtime" in imported or ".providers" in imported
                    ):
                        direct_concrete[target_owner].add(module)

                target_topology_owner = owner_for_module(imported, topology_owners)
                if (
                    target_topology_owner is not None
                    and target_topology_owner != source_topology_owner
                ):
                    topology_inbound[target_topology_owner][channel].add(module)
                    if channel == "production" and (
                        ".runtime" in imported or ".providers" in imported
                    ):
                        topology_direct_concrete[target_topology_owner].add(module)

    # Environment categories are intentionally discovered through the canonical
    # system registry rather than hard-importing every family package. A
    # production consumer of environment.category.composition therefore
    # consumes every registered environment family contract dynamically.
    if dynamic_environment_consumers:
        dynamic_environment_consumers.add(
            "noetrium_platform.capabilities.environment.category.composition.default"
        )
        for key, spec in catalog.items():
            if spec.get("parent") != "environment":
                continue
            provides = spec.get("provides", ())
            if any(
                isinstance(value, str)
                and value.startswith("environment.")
                and value.endswith(".contract")
                for value in provides
            ):
                inbound[str(key)]["production"].update(
                    dynamic_environment_consumers
                )
                composition_inbound[str(key)].update(
                    dynamic_environment_consumers
                )

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
        elif leaf_contract_ready(package_path):
            status = "extensible-leaf-ready"
        elif aggregate_shell_ready(
            package_path,
            tuple(sorted(children_by_key.get(key, ()))),
        ):
            status = "aggregate-ready"
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

    layer_rows: list[LayerIntegrationRow] = []
    children_by_topology: dict[str, list[str]] = defaultdict(list)
    for node_key, (_level, spec) in topology_specs.items():
        parent_key = str(spec.get("parent"))
        children_by_topology[parent_key].append(node_key)

    def descendants(node_key: str) -> tuple[str, ...]:
        result: list[str] = []
        stack = list(children_by_topology.get(node_key, ()))
        while stack:
            child = stack.pop()
            result.append(child)
            stack.extend(children_by_topology.get(child, ()))
        return tuple(result)

    for node_key, (level, spec) in sorted(topology_specs.items()):
        package = str(spec["package_prefix"])
        package_path = ROOT / Path(*package.split("."))
        declared = tuple(str(value) for value in spec.get("shape", ()))
        present = tuple(
            shape
            for shape in declared
            if (package_path / shape).is_dir()
            or (package_path / shape).with_suffix(".py").is_file()
        )
        missing = tuple(shape for shape in declared if shape not in present)
        python_files = tuple(package_path.rglob("*.py")) if package_path.exists() else ()
        production = set(topology_inbound[node_key]["production"])
        research = set(topology_inbound[node_key]["research"])
        scripts = set(topology_inbound[node_key]["script"])
        tests = set(topology_inbound[node_key]["test"])
        concrete = set(topology_direct_concrete[node_key])
        child_keys = descendants(node_key)
        descendant_production: set[str] = set()
        for child_key in child_keys:
            descendant_production.update(
                topology_inbound[child_key]["production"]
            )

        if missing:
            status = "declared-shape-missing"
        elif production:
            status = "production-integrated"
        elif descendant_production:
            status = "aggregate-integrated"
        elif leaf_contract_ready(package_path):
            status = "extensible-leaf-ready"
        elif scripts or research:
            status = "operations-or-research-only"
        elif tests:
            status = "test-only"
        elif python_files:
            status = "implemented-unconsumed"
        else:
            status = "catalog-only"

        layer_rows.append(
            LayerIntegrationRow(
                node_key=node_key,
                topology_level=level,
                system_key=str(spec.get("system")),
                parent_key=str(spec.get("parent")),
                package_prefix=package,
                node_kind=str(spec.get("node_kind", "")),
                declared_shape=declared,
                present_shape=present,
                missing_shape=missing,
                python_file_count=len(python_files),
                production_consumers=tuple(sorted(production)),
                research_consumers=tuple(sorted(research)),
                script_consumers=tuple(sorted(scripts)),
                test_consumers=tuple(sorted(tests)),
                direct_runtime_or_provider_consumers=tuple(sorted(concrete)),
                status=status,
            )
        )

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
        "component_count": sum(
            row.topology_level == "component" for row in layer_rows
        ),
        "internal_facet_count": sum(
            row.topology_level == "internal_facet" for row in layer_rows
        ),
        "layer_status_counts": dict(
            sorted(Counter(row.status for row in layer_rows).items())
        ),
        "layer_disconnected_count": sum(
            row.status in disconnected_statuses for row in layer_rows
        ),
        "layer_attention_nodes": {
            status: tuple(
                row.node_key
                for row in layer_rows
                if row.status == status
            )
            for status in sorted(disconnected_statuses | {"catalog-only"})
            if any(row.status == status for row in layer_rows)
        },
        "topology_errors": tuple(sorted(set(topology_errors))),
        "layers": [asdict(row) for row in layer_rows],
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Noetrium system integration audit",
        "",
        f"- Registered systems: {report['system_count']}",
        f"- Disconnected/non-production-consumed: {report['disconnected_system_count']}",
        f"- Cross-system direct runtime/provider pressure: {report['direct_concrete_dependency_system_count']}",
        f"- Registered components: {report['component_count']}",
        f"- Registered internal facets: {report['internal_facet_count']}",
        f"- Layer nodes needing wiring attention: {report['layer_disconnected_count']}",
        f"- Topology integrity errors: {len(report['topology_errors'])}",
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
        "## Component/internal-facet wiring attention",
        "",
        "| Node | Level | Parent | Status | Prod | Ops/research | Tests |",
        "|---|---|---|---|---:|---:|---:|",
    ]
    for row in report["layers"]:
        if row["status"] in {
            "production-integrated",
            "aggregate-integrated",
            "extensible-leaf-ready",
        }:
            continue
        lines.append(
            "| {key} | {level} | {parent} | {status} | {prod} | {ops} | {tests} |".format(
                key=row["node_key"],
                level=row["topology_level"],
                parent=row["parent_key"],
                status=row["status"],
                prod=len(row["production_consumers"]),
                ops=len(row["script_consumers"]) + len(row["research_consumers"]),
                tests=len(row["test_consumers"]),
            )
        )
    if report["topology_errors"]:
        lines += ["", "## Topology integrity errors", ""]
        lines.extend(f"- {value}" for value in report["topology_errors"])

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
    parser.add_argument("--fail-on-disconnected", action="store_true")
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
        "direct_concrete_dependency_systems": {
            row["system_key"]: row["direct_runtime_or_provider_consumers"]
            for row in report["systems"]
            if row["direct_runtime_or_provider_consumers"]
        },
        "component_count": report["component_count"],
        "internal_facet_count": report["internal_facet_count"],
        "layer_status_counts": report["layer_status_counts"],
        "layer_disconnected_count": report["layer_disconnected_count"],
        "layer_attention_nodes": report["layer_attention_nodes"],
        "topology_errors": report["topology_errors"],
    }, indent=2, sort_keys=True))
    if args.fail_on_shape and (
        report["status_counts"].get("declared-shape-missing", 0)
        or report["status_counts"].get("public-facade-missing", 0)
        or report["layer_status_counts"].get("declared-shape-missing", 0)
        or report["topology_errors"]
    ):
        return 2
    if args.fail_on_disconnected and (
        report["disconnected_system_count"]
        or report["layer_disconnected_count"]
    ):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

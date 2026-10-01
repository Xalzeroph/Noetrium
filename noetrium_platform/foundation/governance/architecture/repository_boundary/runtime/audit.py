from __future__ import annotations

import ast
import json
from pathlib import Path

from ..api import (
    DownstreamImportKind,
    DownstreamImportObservation,
    DownstreamProjectImportReport,
    RepositoryBoundaryReport,
    RepositoryBoundaryViolation,
)


_SCHEMA = "platform-repository-boundary.v2"
_FORBIDDEN_ROOTS = (
    "projects",
    "docs/projects",
)
_CORE_PACKAGE_ROOTS = ("noetrium_platform", "noetrium", "components", "orchestration")
_WORKSPACE_IMPORT_ROOTS = frozenset({"projects", "research", "benchmarks"})

_FRAMEWORK_ENVIRONMENT_DIRS = frozenset({"api", "binding", "catalog", "category", "composition", "instance", "providers", "resolution", "runtime", "specification"})
_BUNDLED_ENVIRONMENT_PROVIDERS = frozenset({"minecraft", "embodied", "gui", "web", "software", "text_world"})

def _violation(code: str, path: str, detail: str) -> RepositoryBoundaryViolation:
    return RepositoryBoundaryViolation(code, path.replace("\\", "/"), detail)


def _audit_forbidden_roots(root: Path) -> list[RepositoryBoundaryViolation]:
    rows: list[RepositoryBoundaryViolation] = []
    for relative in _FORBIDDEN_ROOTS:
        if (root / relative).exists():
            rows.append(_violation("DOWNSTREAM_PATH_IN_UPSTREAM", relative, "downstream-owned path exists in upstream"))
    return rows


def _audit_core_imports(root: Path) -> list[RepositoryBoundaryViolation]:
    rows: list[RepositoryBoundaryViolation] = []
    for package_name in _CORE_PACKAGE_ROOTS:
        package_root = root / package_name
        for path in package_root.rglob("*.py") if package_root.exists() else ():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, SyntaxError, UnicodeError) as exc:
                rows.append(_violation("SOURCE_PARSE_FAILED", str(path.relative_to(root)), str(exc)))
                continue
            for node in ast.walk(tree):
                names: tuple[str, ...] = ()
                if isinstance(node, ast.Import):
                    names = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = (node.module,)
                for name in names:
                    root_name = name.split(".", 1)[0]
                    if root_name not in _WORKSPACE_IMPORT_ROOTS:
                        continue
                    code = (
                        "CORE_IMPORTS_DOWNSTREAM"
                        if root_name == "projects"
                        else "CORE_IMPORTS_RESEARCH_WORKSPACE"
                    )
                    rows.append(_violation(
                        code,
                        str(path.relative_to(root)),
                        f"line {getattr(node, 'lineno', 0)} imports workspace namespace {root_name}",
                    ))
    return rows


def _audit_environment_ownership(root: Path) -> list[RepositoryBoundaryViolation]:
    rows: list[RepositoryBoundaryViolation] = []
    environment_root = root / "noetrium_platform" / "capabilities" / "environment"
    allowed_dirs = _FRAMEWORK_ENVIRONMENT_DIRS | _BUNDLED_ENVIRONMENT_PROVIDERS
    if environment_root.is_dir():
        for child in sorted(environment_root.iterdir(), key=lambda path: path.name):
            if child.is_dir() and not child.name.startswith("__") and child.name not in allowed_dirs:
                rows.append(_violation("CONCRETE_ENVIRONMENT_IN_UPSTREAM", str(child.relative_to(root)), "environment provider is not an approved bundled upstream provider"))
    catalog = root / "noetrium_platform" / "foundation" / "governance" / "system_registry" / "catalog.json"
    if catalog.is_file():
        try:
            payload = json.loads(catalog.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            rows.append(_violation("SYSTEM_CATALOG_INVALID", str(catalog.relative_to(root)), str(exc)))
            return rows
        if isinstance(payload, dict):
            prefix = "noetrium_platform.capabilities.environment"
            for key, descriptor in payload.items():
                if not (key == "environment" or key.startswith("environment/")):
                    continue
                package_prefix = descriptor.get("package_prefix") if isinstance(descriptor, dict) else None
                if not isinstance(package_prefix, str):
                    rows.append(_violation(
                        "SYSTEM_CATALOG_INVALID",
                        str(catalog.relative_to(root)),
                        f"environment system has no package_prefix: {key}",
                    ))
                    continue
                if package_prefix == prefix:
                    continue
                if not package_prefix.startswith(prefix + "."):
                    rows.append(_violation(
                        "REGISTRY_OWNS_DOWNSTREAM_ENVIRONMENT",
                        str(catalog.relative_to(root)),
                        f"environment system escapes environment package authority: {key}",
                    ))
                    continue
                first_segment = package_prefix[len(prefix) + 1:].split(".", 1)[0]
                if first_segment not in allowed_dirs:
                    rows.append(_violation(
                        "REGISTRY_OWNS_DOWNSTREAM_ENVIRONMENT",
                        str(catalog.relative_to(root)),
                        f"unapproved environment provider package: {key} -> {package_prefix}",
                    ))
    return rows


def _audit_metadata(root: Path) -> list[RepositoryBoundaryViolation]:
    rows: list[RepositoryBoundaryViolation] = []
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8")
        for namespace in ("projects", "research", "benchmarks"):
            if f'{namespace}*' in text or f'{namespace}.' in text:
                code = "PACKAGE_INCLUDES_DOWNSTREAM" if namespace == "projects" else "PACKAGE_INCLUDES_RESEARCH_WORKSPACE"
                rows.append(_violation(code, "pyproject.toml", f"package discovery includes workspace namespace {namespace}"))

    dockerfile = root / "deploy" / "Dockerfile"
    if dockerfile.is_file():
        text = dockerfile.read_text(encoding="utf-8").lower()
        for namespace in ("projects", "research", "benchmarks"):
            if f"copy {namespace}" in text:
                code = "IMAGE_COPIES_DOWNSTREAM" if namespace == "projects" else "IMAGE_COPIES_RESEARCH_WORKSPACE"
                rows.append(_violation(code, "deploy/Dockerfile", f"generic image copies workspace namespace {namespace}"))
    return rows


def _audit_release_manifest(root: Path) -> list[RepositoryBoundaryViolation]:
    manifest = root / "RELEASE_MANIFEST.json"
    if not manifest.is_file():
        return []
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [_violation("RELEASE_MANIFEST_INVALID", "RELEASE_MANIFEST.json", str(exc))]
    text = json.dumps(payload, sort_keys=True)
    forbidden = ("projects/", "research/", "benchmarks/", "docs/projects/", "docs/research/")
    if any(token in text for token in forbidden):
        return [_violation("RELEASE_INCLUDES_DOWNSTREAM", "RELEASE_MANIFEST.json", "release inventory contains downstream-owned paths")]
    return []


def audit_repository_boundary(root: Path, *, include_release_manifest: bool = True) -> RepositoryBoundaryReport:
    resolved = Path(root).resolve()
    violations = (
        _audit_forbidden_roots(resolved)
        + _audit_core_imports(resolved)
        + _audit_environment_ownership(resolved)
        + _audit_metadata(resolved)
        + (_audit_release_manifest(resolved) if include_release_manifest else [])
    )
    ordered = tuple(sorted(violations, key=lambda row: (row.code, row.path, row.detail)))
    return RepositoryBoundaryReport(_SCHEMA, ordered)


_DOWNSTREAM_IMPORT_SCHEMA = "downstream-project-import-policy.v2"
_DOWNSTREAM_SCAN_EXCLUDES = frozenset({
    ".git", ".hg", ".mypy_cache", ".noetrium", ".pytest_cache", ".ruff_cache", ".tox",
    ".venv", "__pycache__", "build", "dist", "node_modules", "venv",
})


def _downstream_import_kind(module: str) -> DownstreamImportKind:
    if module == "noetrium" or module == "noetrium.api":
        return DownstreamImportKind.NOETRIUM_API
    if (
        module.startswith("noetrium.")
        or module == "noetrium_platform"
        or module.startswith("noetrium_platform.")
        or module == "components"
        or module.startswith("components.")
        or module == "orchestration"
        or module.startswith("orchestration.")
    ):
        return DownstreamImportKind.FORBIDDEN_INTERNAL
    return DownstreamImportKind.EXTERNAL


def _source_import_modules(tree: ast.AST) -> tuple[tuple[int, str], ...]:
    rows: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            rows.extend((getattr(node, "lineno", 0), alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            rows.append((getattr(node, "lineno", 0), node.module))
    return tuple(rows)


def audit_downstream_project_imports(root: Path) -> DownstreamProjectImportReport:
    """Classify downstream imports and reject Platform-private implementation use.

    The downstream root is intentionally independent of the upstream repository.
    A vendored ``noetrium_platform`` package is itself a violation even when its
    internal imports would otherwise parse.
    """

    resolved = Path(root).resolve()
    observations: list[DownstreamImportObservation] = []
    violations: list[RepositoryBoundaryViolation] = []
    vendored = resolved / "noetrium_platform"
    if vendored.exists():
        violations.append(_violation(
            "DOWNSTREAM_VENDORS_PLATFORM",
            "noetrium_platform",
            "downstream project must depend on the qualified Platform artifact instead of vendoring it",
        ))
    for path in sorted(resolved.rglob("*.py"), key=lambda row: row.as_posix()):
        relative = path.relative_to(resolved)
        if any(part in _DOWNSTREAM_SCAN_EXCLUDES for part in relative.parts):
            continue
        if relative.parts and relative.parts[0] == "noetrium_platform":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            violations.append(_violation("DOWNSTREAM_SOURCE_PARSE_FAILED", str(relative), str(exc)))
            continue
        for line, module in _source_import_modules(tree):
            kind = _downstream_import_kind(module)
            observations.append(DownstreamImportObservation(
                str(relative).replace("\\", "/"), line, module, kind
            ))
            if kind is DownstreamImportKind.FORBIDDEN_INTERNAL:
                violations.append(_violation(
                    "DOWNSTREAM_NON_UNIFIED_NOETRIUM_IMPORT",
                    str(relative),
                    f"line {line} bypasses the single noetrium.api entrypoint via {module}",
                ))
    return DownstreamProjectImportReport(
        _DOWNSTREAM_IMPORT_SCHEMA,
        tuple(sorted(observations)),
        tuple(sorted(violations, key=lambda row: (row.code, row.path, row.detail))),
    )


__all__ = ["audit_downstream_project_imports", "audit_repository_boundary"]

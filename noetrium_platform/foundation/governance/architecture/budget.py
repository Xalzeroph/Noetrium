from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable

from noetrium_platform.foundation.governance.api import RepositorySourceIndexPort
from noetrium_platform.foundation.governance.system_registry.api import system_catalog


_BUDGET_FIELDS = (
    "top_level_systems",
    "subsystems",
    "contract_declarations",
    "authorities",
    "import_edges",
)
_BUDGET_PATH = Path("noetrium_platform/foundation/governance/architecture/ARCHITECTURE_BUDGET.json")
_SCHEMA_VERSION = "noetrium.architecture-budget.v1"
_SHA256_LEN = 64


@dataclass(frozen=True, slots=True)
class ArchitectureComplexity:
    top_level_systems: int
    subsystems: int
    contract_declarations: int
    authorities: int
    import_edges: int


@dataclass(frozen=True, slots=True)
class ArchitectureBaselineAuthority:
    architecture_digest: str
    complexity: ArchitectureComplexity


@dataclass(frozen=True, slots=True)
class ArchitectureComplexityBudget:
    schema_version: str
    baseline: ArchitectureBaselineAuthority
    effective_limits: ArchitectureComplexity

    @property
    def limits(self) -> ArchitectureComplexity:
        return self.effective_limits


@dataclass(frozen=True, slots=True)
class ArchitectureBudgetViolation:
    dimension: str
    observed: int
    limit: int
    detail: str


class ArchitectureBudgetProvenanceError(RuntimeError):
    pass


def _decode_complexity(value: object, *, field: str) -> ArchitectureComplexity:
    if not isinstance(value, dict) or set(value) != set(_BUDGET_FIELDS):
        raise ValueError(f"{field} must define exactly {', '.join(_BUDGET_FIELDS)}")
    decoded: dict[str, int] = {}
    for key in _BUDGET_FIELDS:
        raw = value[key]
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise ValueError(f"{field}.{key} must be a non-negative integer")
        decoded[key] = raw
    return ArchitectureComplexity(**decoded)


def _canonical_digest(value: object, *, field: str) -> str:
    text = str(value)
    if len(text) != _SHA256_LEN or any(ch not in "0123456789abcdef" for ch in text):
        raise ValueError(f"{field} must be an exact lowercase SHA-256 digest")
    return text


def architecture_baseline_digest(
    complexity: ArchitectureComplexity,
    *,
    import_edge_pairs: Iterable[tuple[str, str]],
) -> str:
    """Return the content identity of the architecture topology being approved.

    The identity intentionally depends on structural facts rather than a Git commit.
    This lets a release root commit carry its own complete architecture baseline while
    still detecting topology drift, including import-edge substitutions that preserve
    the aggregate edge count.
    """

    pairs = tuple(sorted(set((str(source), str(target)) for source, target in import_edge_pairs)))
    payload = {
        "schema": "noetrium.architecture-baseline.v1",
        "complexity": {field: getattr(complexity, field) for field in _BUDGET_FIELDS},
        "import_edges": pairs,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def current_architecture_complexity(*, import_edges: int) -> ArchitectureComplexity:
    rows = tuple(system_catalog())
    return ArchitectureComplexity(
        top_level_systems=sum(row.topology_parent_key is None for row in rows),
        subsystems=sum(row.topology_parent_key is not None for row in rows),
        contract_declarations=sum(len(row.requires) + len(row.provides) for row in rows),
        authorities=len(rows),
        import_edges=int(import_edges),
    )


def source_catalog_complexity(
    source_index: RepositorySourceIndexPort,
    *,
    import_edges: int,
) -> ArchitectureComplexity:
    catalog_path = "noetrium_platform/foundation/governance/system_registry/catalog.json"
    try:
        document = json.loads(source_index.text(catalog_path))
    except (KeyError, json.JSONDecodeError) as exc:
        raise ArchitectureBudgetProvenanceError(
            "canonical system catalog is absent or invalid in the immutable source cut"
        ) from exc
    if not isinstance(document, dict) or any(not isinstance(row, dict) for row in document.values()):
        raise ArchitectureBudgetProvenanceError("canonical system catalog has invalid shape")
    rows = tuple(document.values())
    return ArchitectureComplexity(
        top_level_systems=sum(row.get("parent") is None for row in rows),
        subsystems=sum(row.get("parent") is not None for row in rows),
        contract_declarations=sum(
            len(row.get("requires", ())) + len(row.get("provides", ())) for row in rows
        ),
        authorities=sum(bool(row.get("authority")) for row in rows),
        import_edges=int(import_edges),
    )


def load_architecture_complexity_budget(
    root: Path,
    *,
    source_index: RepositorySourceIndexPort | None = None,
) -> ArchitectureComplexityBudget:
    path = Path(root).resolve() / _BUDGET_PATH
    try:
        raw = source_index.text(_BUDGET_PATH.as_posix()) if source_index is not None else path.read_text(encoding="utf-8")
        document = json.loads(raw)
    except (OSError, KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"architecture complexity budget unavailable: {path}") from exc
    expected = {"schema_version", "architecture_digest", "limits"}
    if not isinstance(document, dict) or set(document) != expected:
        raise ValueError("architecture complexity budget has unexpected fields")
    if document["schema_version"] != _SCHEMA_VERSION:
        raise ValueError("unsupported architecture complexity budget schema")
    limits = _decode_complexity(document["limits"], field="limits")
    return ArchitectureComplexityBudget(
        schema_version=_SCHEMA_VERSION,
        baseline=ArchitectureBaselineAuthority(
            architecture_digest=_canonical_digest(document["architecture_digest"], field="architecture_digest"),
            complexity=limits,
        ),
        effective_limits=limits,
    )


def verify_architecture_baseline_authority(
    budget: ArchitectureComplexityBudget,
    *,
    architecture_digest: str,
    complexity: ArchitectureComplexity,
) -> None:
    observed = _canonical_digest(architecture_digest, field="observed architecture_digest")
    mismatches: list[str] = []
    if observed != budget.baseline.architecture_digest:
        mismatches.append(
            f"architecture_digest observed={observed} expected={budget.baseline.architecture_digest}"
        )
    if complexity != budget.baseline.complexity:
        mismatches.append(f"complexity observed={complexity!r} expected={budget.baseline.complexity!r}")
    if mismatches:
        raise ArchitectureBudgetProvenanceError(
            "architecture baseline authority mismatch: " + "; ".join(mismatches)
        )


def audit_architecture_complexity_budget(
    root: Path,
    *,
    import_edges: int,
    import_edge_pairs: Iterable[tuple[str, str]] = (),
    source_index: RepositorySourceIndexPort | None = None,
) -> tuple[
    ArchitectureComplexity,
    ArchitectureComplexityBudget | None,
    tuple[ArchitectureBudgetViolation, ...],
]:
    pairs = tuple(import_edge_pairs)
    if source_index is not None:
        marker = "noetrium_platform/foundation/governance/architecture/report.py"
        if not any(blob.relative_path == marker for blob in source_index.documents(suffixes={".py"})):
            return ArchitectureComplexity(0, 0, 0, 0, import_edges), None, ()
        current = source_catalog_complexity(source_index, import_edges=import_edges)
    else:
        current = current_architecture_complexity(import_edges=import_edges)
    budget = load_architecture_complexity_budget(root, source_index=source_index)
    observed_digest = architecture_baseline_digest(current, import_edge_pairs=pairs)
    violations: list[ArchitectureBudgetViolation] = []
    if observed_digest != budget.baseline.architecture_digest:
        violations.append(
            ArchitectureBudgetViolation(
                dimension="architecture_digest",
                observed=1,
                limit=0,
                detail=(
                    "architecture topology differs from the approved baseline: "
                    f"observed={observed_digest} expected={budget.baseline.architecture_digest}; "
                    "review the change and explicitly regenerate ARCHITECTURE_BUDGET.json"
                ),
            )
        )
    for field in _BUDGET_FIELDS:
        observed = getattr(current, field)
        limit = getattr(budget.limits, field)
        if observed > limit:
            violations.append(
                ArchitectureBudgetViolation(
                    dimension=field,
                    observed=observed,
                    limit=limit,
                    detail=f"{field} complexity budget exceeded: observed={observed} limit={limit}",
                )
            )
    return current, budget, tuple(violations)


__all__ = [
    "ArchitectureBaselineAuthority",
    "ArchitectureBudgetProvenanceError",
    "ArchitectureBudgetViolation",
    "ArchitectureComplexity",
    "ArchitectureComplexityBudget",
    "architecture_baseline_digest",
    "audit_architecture_complexity_budget",
    "current_architecture_complexity",
    "load_architecture_complexity_budget",
    "source_catalog_complexity",
    "verify_architecture_baseline_authority",
]

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import re
from typing import Callable, Iterable

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
_SCHEMA_VERSION = "architecture-complexity-budget.v3"
_APPROVAL_SET_SCHEMA = "supervisor.architecture-migration-approval-set.v1"
_APPROVAL_SCHEMA_V1 = "supervisor.architecture-migration-approval.v1"
_APPROVAL_SCHEMA_V2 = "supervisor.architecture-migration-approval.v2"
_IMPORT_ONLY_APPROVAL_SCOPE = "architecture-import-edge-migration-only"
_COMPLEXITY_APPROVAL_SCOPE = "architecture-complexity-migration-only"
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_ROLE_RE = re.compile(r"ROLE[0-9]{2}")
_MIGRATION_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{2,127}")
_MODULE_PREFIX_RE = re.compile(r"noetrium_platform(?:\.[a-z_][a-z0-9_]*)+")
_SOURCE_SUFFIXES = frozenset({
    ".py", ".js", ".mjs", ".cjs", ".sh", ".bash",
    ".json", ".yaml", ".yml", ".toml",
})


@dataclass(frozen=True, slots=True)
class ArchitectureComplexity:
    top_level_systems: int
    subsystems: int
    contract_declarations: int
    authorities: int
    import_edges: int


@dataclass(frozen=True, slots=True)
class ArchitectureBaselineAuthority:
    git_sha: str
    source_digest: str
    complexity: ArchitectureComplexity


@dataclass(frozen=True, slots=True)
class ArchitectureMigrationAllowance:
    migration_id: str
    owner_role: str
    delta: ArchitectureComplexity
    justification: str
    module_prefixes: tuple[str, ...]
    import_projection_sha256: str | None

@dataclass(frozen=True, slots=True)
class ArchitectureMigrationApproval:
    schema_version: str
    migration_id: str
    source_git_sha: str
    source_digest: str
    complexity_delta: ArchitectureComplexity
    decision: str
    authority: str
    scope: str
    review_state: str
    review_evidence_refs: tuple[str, ...]
    issued_at: str
    note: str
    approval_record_sha256: str

    @property
    def approved(self) -> bool:
        return self.decision == "approved"


@dataclass(frozen=True, slots=True)
class ArchitectureMigrationApprovalSet:
    schema_version: str
    authority: str
    baseline_git_sha: str
    approvals: tuple[ArchitectureMigrationApproval, ...]
    default_decision: str
    rule: str


@dataclass(frozen=True, slots=True)
class ArchitectureMigrationObservation:
    complexity: ArchitectureComplexity
    import_projection_sha256: str | None
    owner_source_sha256: str | None

@dataclass(frozen=True, slots=True)
class ArchitectureComplexityBudget:
    schema_version: str
    baseline: ArchitectureBaselineAuthority
    migrations: tuple[ArchitectureMigrationAllowance, ...]
    effective_limits: ArchitectureComplexity
    applicable_migration_ids: tuple[str, ...]

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


def _canonical_json_sha256(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _canonical_git_sha(value: object, *, field: str) -> str:
    text = str(value)
    if _GIT_SHA_RE.fullmatch(text) is None:
        raise ValueError(f"{field} must be an exact lowercase 40-character Git SHA")
    return text

def _canonical_sha256(value: object, *, field: str) -> str:
    text = str(value)
    if _SHA256_RE.fullmatch(text) is None:
        raise ValueError(f"{field} must be an exact lowercase SHA-256 digest")
    return text


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


def _decode_delta(value: object, *, field: str) -> ArchitectureComplexity:
    if not isinstance(value, dict) or set(value) != set(_BUDGET_FIELDS):
        raise ValueError(f"{field} must define exactly {', '.join(_BUDGET_FIELDS)}")
    decoded: dict[str, int] = {}
    for key in _BUDGET_FIELDS:
        raw = value[key]
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ValueError(f"{field}.{key} must be an integer")
        decoded[key] = raw
    return ArchitectureComplexity(**decoded)


def _apply_complexity_delta(
    base: ArchitectureComplexity,
    delta: ArchitectureComplexity,
    *,
    field: str,
) -> ArchitectureComplexity:
    values = {
        key: getattr(base, key) + getattr(delta, key)
        for key in _BUDGET_FIELDS
    }
    negative = tuple(key for key, value in values.items() if value < 0)
    if negative:
        raise ValueError(f"{field} produces negative complexity: {', '.join(negative)}")
    return ArchitectureComplexity(**values)


def _decode_baseline(value: object) -> ArchitectureBaselineAuthority:
    if not isinstance(value, dict) or set(value) != {"git_sha", "source_digest", "complexity"}:
        raise ValueError("baseline must define exactly git_sha, source_digest and complexity")
    return ArchitectureBaselineAuthority(
        git_sha=_canonical_git_sha(value["git_sha"], field="baseline.git_sha"),
        source_digest=_canonical_sha256(value["source_digest"], field="baseline.source_digest"),
        complexity=_decode_complexity(value["complexity"], field="baseline.complexity"),
    )


def _decode_applicability(value: object, *, index: int) -> tuple[tuple[str, ...], str | None]:
    if value is None:
        return (), None
    expected = {"module_prefixes", "import_projection_sha256"}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"migrations[{index}].applicability has unexpected fields")
    raw_prefixes = value["module_prefixes"]
    if not isinstance(raw_prefixes, list) or not raw_prefixes:
        raise ValueError(f"migrations[{index}].applicability.module_prefixes must be non-empty")
    prefixes = tuple(str(item) for item in raw_prefixes)
    if len(prefixes) != len(set(prefixes)):
        raise ValueError(f"migrations[{index}].applicability.module_prefixes must be unique")
    if any(_MODULE_PREFIX_RE.fullmatch(prefix) is None for prefix in prefixes):
        raise ValueError(f"migrations[{index}].applicability.module_prefixes are not canonical")
    projection = _canonical_sha256(
        value["import_projection_sha256"],
        field=f"migrations[{index}].applicability.import_projection_sha256",
    )
    return prefixes, projection


def _decode_migration(value: object, *, index: int) -> ArchitectureMigrationAllowance:
    expected = {
        "migration_id", "owner_role", "delta", "justification", "applicability",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"migrations[{index}] has unexpected fields")
    migration_id = str(value["migration_id"])
    if _MIGRATION_ID_RE.fullmatch(migration_id) is None:
        raise ValueError(f"migrations[{index}].migration_id is not canonical")
    owner_role = str(value["owner_role"])
    if _ROLE_RE.fullmatch(owner_role) is None:
        raise ValueError(f"migrations[{index}].owner_role must use ROLE## identity")
    justification = str(value["justification"]).strip()
    if len(justification) < 48:
        raise ValueError(f"migrations[{index}].justification must be substantive")
    delta = _decode_delta(value["delta"], field=f"migrations[{index}].delta")
    if all(getattr(delta, field) == 0 for field in _BUDGET_FIELDS):
        raise ValueError(f"migrations[{index}].delta must contain architecture change")
    module_prefixes, projection = _decode_applicability(value["applicability"], index=index)
    return ArchitectureMigrationAllowance(
        migration_id=migration_id,
        owner_role=owner_role,
        delta=delta,
        justification=justification,
        module_prefixes=module_prefixes,
        import_projection_sha256=projection,
    )

def load_architecture_complexity_budget(
    root: Path,
    *,
    source_index: RepositorySourceIndexPort | None = None,
) -> ArchitectureComplexityBudget:
    path = Path(root).resolve() / _BUDGET_PATH
    try:
        raw = (
            source_index.text(_BUDGET_PATH.as_posix())
            if source_index is not None
            else path.read_text(encoding="utf-8")
        )
        document = json.loads(raw)
    except (OSError, KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"architecture complexity budget unavailable: {path}") from exc
    if not isinstance(document, dict) or set(document) != {"schema_version", "baseline", "migrations"}:
        raise ValueError("architecture complexity budget has unexpected fields")
    if document["schema_version"] != _SCHEMA_VERSION:
        raise ValueError("unsupported architecture complexity budget schema")
    baseline = _decode_baseline(document["baseline"])
    raw_migrations = document["migrations"]
    if not isinstance(raw_migrations, list):
        raise ValueError("migrations must be a JSON array")
    migrations = tuple(_decode_migration(item, index=i) for i, item in enumerate(raw_migrations))
    for migration in migrations:
        _apply_complexity_delta(
            baseline.complexity,
            migration.delta,
            field=f"migration {migration.migration_id}",
        )
    ids = tuple(item.migration_id for item in migrations)
    if len(ids) != len(set(ids)):
        raise ValueError("migration_id values must be unique")
    return ArchitectureComplexityBudget(
        schema_version=_SCHEMA_VERSION,
        baseline=baseline,
        migrations=migrations,
        effective_limits=baseline.complexity,
        applicable_migration_ids=(),
    )


def _decode_approval(value: object, *, index: int) -> ArchitectureMigrationApproval:
    if not isinstance(value, dict):
        raise ValueError(f"approvals[{index}] must be an object")
    schema = str(value.get("schema", ""))
    common = {
        "schema", "migration_id", "source_sha", "source_digest", "decision",
        "authority", "scope", "review_state", "review_evidence_refs", "issued_at",
        "note", "approval_record_sha256",
    }
    if schema == _APPROVAL_SCHEMA_V1:
        expected = common | {"dimension", "delta"}
    elif schema == _APPROVAL_SCHEMA_V2:
        expected = common | {"complexity_delta"}
    else:
        raise ValueError(f"approvals[{index}] has unsupported schema")
    if set(value) != expected:
        raise ValueError(f"approvals[{index}] has unexpected fields")
    migration_id = str(value["migration_id"])
    if _MIGRATION_ID_RE.fullmatch(migration_id) is None:
        raise ValueError(f"approvals[{index}].migration_id is not canonical")
    if schema == _APPROVAL_SCHEMA_V1:
        dimension = str(value["dimension"])
        if dimension != "import_edges":
            raise ValueError(f"approvals[{index}].dimension must be import_edges")
        raw_delta = value["delta"]
        if isinstance(raw_delta, bool) or not isinstance(raw_delta, int) or raw_delta <= 0:
            raise ValueError(f"approvals[{index}].delta must be a positive integer")
        complexity_delta = ArchitectureComplexity(0, 0, 0, 0, raw_delta)
    else:
        complexity_delta = _decode_delta(
            value["complexity_delta"], field=f"approvals[{index}].complexity_delta"
        )
        if not any(getattr(complexity_delta, field) for field in _BUDGET_FIELDS):
            raise ValueError(f"approvals[{index}].complexity_delta must be non-zero")
    decision = str(value["decision"])
    if decision not in {"approved", "not_approved"}:
        raise ValueError(f"approvals[{index}].decision is invalid")
    authority = str(value["authority"])
    if authority != "ROLE00":
        raise ValueError(f"approvals[{index}].authority must be ROLE00")
    scope = str(value["scope"])
    expected_scope = (
        _IMPORT_ONLY_APPROVAL_SCOPE if schema == _APPROVAL_SCHEMA_V1
        else _COMPLEXITY_APPROVAL_SCOPE
    )
    if scope != expected_scope:
        raise ValueError(f"approvals[{index}].scope must be {expected_scope}")
    refs = value["review_evidence_refs"]
    if not isinstance(refs, list) or not refs or any(
        not isinstance(ref, str) or not ref.strip() for ref in refs
    ):
        raise ValueError(f"approvals[{index}].review_evidence_refs must be non-empty strings")
    expected_digest = _canonical_sha256(
        value["approval_record_sha256"], field=f"approvals[{index}].approval_record_sha256"
    )
    digest_payload = {key: item for key, item in value.items() if key != "approval_record_sha256"}
    if _canonical_json_sha256(digest_payload) != expected_digest:
        raise ArchitectureBudgetProvenanceError(
            f"approval record digest mismatch: {migration_id}"
        )
    return ArchitectureMigrationApproval(
        schema_version=schema,
        migration_id=migration_id,
        source_git_sha=_canonical_git_sha(value["source_sha"], field=f"approvals[{index}].source_sha"),
        source_digest=_canonical_sha256(value["source_digest"], field=f"approvals[{index}].source_digest"),
        complexity_delta=complexity_delta,
        decision=decision,
        authority=authority,
        scope=scope,
        review_state=str(value["review_state"]),
        review_evidence_refs=tuple(str(ref) for ref in refs),
        issued_at=str(value["issued_at"]),
        note=str(value["note"]),
        approval_record_sha256=expected_digest,
    )

def load_architecture_migration_approval_set(
    path: Path,
    *,
    expected_sha256: str,
) -> ArchitectureMigrationApprovalSet:
    source = Path(path).resolve()
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise ArchitectureBudgetProvenanceError(
            f"architecture migration approval set unavailable: {source}"
        ) from exc
    expected = _canonical_sha256(expected_sha256, field="approval set SHA-256")
    observed = hashlib.sha256(raw).hexdigest()
    if observed != expected:
        raise ArchitectureBudgetProvenanceError(
            f"approval set digest mismatch: observed={observed} expected={expected}"
        )
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchitectureBudgetProvenanceError("approval set is not canonical UTF-8 JSON") from exc
    expected_fields = {
        "schema", "authority", "baseline_sha", "approvals", "default_decision", "rule",
    }
    if not isinstance(document, dict) or set(document) != expected_fields:
        raise ValueError("architecture migration approval set has unexpected fields")
    if document["schema"] != _APPROVAL_SET_SCHEMA or document["authority"] != "ROLE00":
        raise ValueError("unsupported architecture migration approval authority")
    if document["default_decision"] != "not_approved":
        raise ValueError("approval set default_decision must be not_approved")
    raw_approvals = document["approvals"]
    if not isinstance(raw_approvals, list):
        raise ValueError("approval set approvals must be an array")
    approvals = tuple(_decode_approval(item, index=i) for i, item in enumerate(raw_approvals))
    ids = tuple(item.migration_id for item in approvals)
    if len(ids) != len(set(ids)):
        raise ValueError("approval set migration_id values must be unique")
    return ArchitectureMigrationApprovalSet(
        schema_version=_APPROVAL_SET_SCHEMA,
        authority="ROLE00",
        baseline_git_sha=_canonical_git_sha(document["baseline_sha"], field="approval set baseline_sha"),
        approvals=approvals,
        default_decision="not_approved",
        rule=str(document["rule"]),
    )

def import_projection_digest(
    import_edge_pairs: Iterable[tuple[str, str]],
    module_prefixes: Iterable[str],
) -> str:
    prefixes = tuple(module_prefixes)
    pairs = sorted(
        (str(source), str(target))
        for source, target in import_edge_pairs
        if any(source == prefix or source.startswith(prefix + ".") for prefix in prefixes)
    )
    return _canonical_json_sha256(pairs)


def source_scope_digest(
    source_index: RepositorySourceIndexPort,
    module_prefixes: Iterable[str],
) -> str:
    bases = tuple(prefix.replace(".", "/") for prefix in module_prefixes)
    rows = sorted(
        (blob.relative_path, blob.sha256)
        for blob in source_index.documents(suffixes=_SOURCE_SUFFIXES)
        if any(
            blob.relative_path == base + ".py" or blob.relative_path.startswith(base + "/")
            for base in bases
        )
    )
    return _canonical_json_sha256(rows)


def _module_in_scope(module: str, module_prefixes: Iterable[str]) -> bool:
    return any(module == prefix or module.startswith(prefix + ".") for prefix in module_prefixes)


def _module_in_budget_scope(module: str, module_prefixes: Iterable[str]) -> bool:
    """Account for moved composition roots without reviving kernel ownership."""
    prefixes = tuple(module_prefixes)
    if _module_in_scope(module, prefixes):
        return True
    return (
        "noetrium_platform.foundation.kernel" in prefixes
        and (
            module == "noetrium_platform.composition"
            or module.startswith("noetrium_platform.composition.")
        )
    )


def _scope_owns_catalog(module_prefixes: Iterable[str]) -> bool:
    # The canonical topology/catalog is ROLE01 Governance-owned source.
    return "noetrium_platform.foundation.governance" in tuple(module_prefixes)


def _registered_extension_scopes() -> tuple[tuple[str, ...], ...]:
    """Return registered downstream and public-contract source roots.

    Reference components and orchestration are downstream extension planes. The
    ``noetrium`` package is the stable public-contract plane consumed by those
    extensions and operator adapters. All three participate in import-budget
    partitioning, but none owns the platform catalog dimensions.
    """
    prefixes = {
        row.package_prefix
        for row in system_catalog()
        if row.package_prefix and not row.package_prefix.startswith("noetrium_platform.")
    }
    prefixes.add("noetrium")
    return tuple((prefix,) for prefix in sorted(prefixes))


def scoped_architecture_complexity(
    global_complexity: ArchitectureComplexity,
    *,
    import_edge_pairs: Iterable[tuple[str, str]],
    module_prefixes: Iterable[str],
) -> ArchitectureComplexity:
    prefixes = tuple(module_prefixes)
    owns_catalog = _scope_owns_catalog(prefixes)
    return ArchitectureComplexity(
        top_level_systems=global_complexity.top_level_systems if owns_catalog else 0,
        subsystems=global_complexity.subsystems if owns_catalog else 0,
        contract_declarations=global_complexity.contract_declarations if owns_catalog else 0,
        authorities=global_complexity.authorities if owns_catalog else 0,
        import_edges=sum(
            1 for source, _target in import_edge_pairs if _module_in_budget_scope(str(source), prefixes)
        ),
    )


def _scopes_overlap(left: Iterable[str], right: Iterable[str]) -> bool:
    return any(
        a == b or a.startswith(b + ".") or b.startswith(a + ".")
        for a in left for b in right
    )


def current_architecture_complexity(*, import_edges: int) -> ArchitectureComplexity:
    descriptors = system_catalog()
    return ArchitectureComplexity(
        top_level_systems=sum(row.identity.is_system for row in descriptors),
        subsystems=sum(not row.identity.is_system for row in descriptors),
        contract_declarations=sum(len(row.requires) + len(row.provides) for row in descriptors),
        authorities=sum(len(row.authorities) for row in descriptors),
        import_edges=int(import_edges),
    )


def source_catalog_complexity(
    source_index: RepositorySourceIndexPort,
    *,
    import_edges: int,
) -> ArchitectureComplexity:
    catalog_path = "noetrium_platform/foundation/governance/system_registry/catalog.json"
    try:
        document_text = source_index.text(catalog_path)
    except KeyError as exc:
        raise ArchitectureBudgetProvenanceError(
            "canonical system catalog is absent from the immutable source cut"
        ) from exc
    document = json.loads(document_text)
    if not isinstance(document, dict):
        raise ArchitectureBudgetProvenanceError("canonical system catalog is not an object")
    rows = tuple(document.values())
    if any(not isinstance(row, dict) for row in rows):
        raise ArchitectureBudgetProvenanceError("canonical system catalog contains non-object rows")
    return ArchitectureComplexity(
        top_level_systems=sum(row.get("parent") is None for row in rows),
        subsystems=sum(row.get("parent") is not None for row in rows),
        contract_declarations=sum(
            len(row.get("requires", ())) + len(row.get("provides", ())) for row in rows
        ),
        authorities=sum(bool(row.get("authority")) for row in rows),
        import_edges=int(import_edges),
    )


def verify_architecture_baseline_authority(
    budget: ArchitectureComplexityBudget,
    *,
    git_sha: str,
    source_digest: str,
    complexity: ArchitectureComplexity,
) -> None:
    mismatches: list[str] = []
    canonical_git_sha = _canonical_git_sha(git_sha, field="observed baseline git_sha")
    canonical_source_digest = _canonical_sha256(source_digest, field="observed baseline source_digest")
    if canonical_git_sha != budget.baseline.git_sha:
        mismatches.append(f"git_sha observed={canonical_git_sha} expected={budget.baseline.git_sha}")
    if canonical_source_digest != budget.baseline.source_digest:
        mismatches.append(
            f"source_digest observed={canonical_source_digest} expected={budget.baseline.source_digest}"
        )
    if complexity != budget.baseline.complexity:
        mismatches.append(f"complexity observed={complexity!r} expected={budget.baseline.complexity!r}")
    if mismatches:
        raise ArchitectureBudgetProvenanceError(
            "architecture baseline authority mismatch: " + "; ".join(mismatches)
        )


_HistoricalObservationResolver = Callable[
    [str, tuple[str, ...]],
    tuple[str, ArchitectureMigrationObservation],
]


def _expected_migration_complexity(
    baseline: ArchitectureComplexity,
    delta: ArchitectureComplexity,
) -> ArchitectureComplexity:
    return _apply_complexity_delta(baseline, delta, field="architecture migration delta")

def _validated_approval_observations(
    budget: ArchitectureComplexityBudget,
    approval_set: ArchitectureMigrationApprovalSet | None,
    historical_observation_resolver: _HistoricalObservationResolver | None,
) -> dict[str, ArchitectureMigrationObservation]:
    if historical_observation_resolver is None:
        raise ArchitectureBudgetProvenanceError(
            "formal architecture budget verification requires historical Git observations"
        )
    baseline_digest, baseline_observation = historical_observation_resolver(
        budget.baseline.git_sha, ()
    )
    verify_architecture_baseline_authority(
        budget,
        git_sha=budget.baseline.git_sha,
        source_digest=baseline_digest,
        complexity=baseline_observation.complexity,
    )
    if approval_set is None:
        return {}
    if approval_set.baseline_git_sha != budget.baseline.git_sha:
        raise ArchitectureBudgetProvenanceError(
            "external approval set baseline does not match architecture budget baseline"
        )
    migrations = {item.migration_id: item for item in budget.migrations}
    baseline_scopes: dict[tuple[str, ...], ArchitectureMigrationObservation] = {}
    validated: dict[str, ArchitectureMigrationObservation] = {}
    for approval in approval_set.approvals:
        if not approval.approved:
            continue
        migration = migrations.get(approval.migration_id)
        if migration is None or not migration.module_prefixes or migration.import_projection_sha256 is None:
            continue
        if approval.complexity_delta != migration.delta:
            continue
        if approval.schema_version == _APPROVAL_SCHEMA_V1 and any(
            getattr(migration.delta, field) != 0
            for field in _BUDGET_FIELDS if field != "import_edges"
        ):
            continue
        if not _scope_owns_catalog(migration.module_prefixes) and any(
            getattr(migration.delta, field) != 0
            for field in _BUDGET_FIELDS if field != "import_edges"
        ):
            continue
        baseline_scope = baseline_scopes.get(migration.module_prefixes)
        if baseline_scope is None:
            _baseline_scope_digest, baseline_scope = historical_observation_resolver(
                budget.baseline.git_sha, migration.module_prefixes
            )
            baseline_scopes[migration.module_prefixes] = baseline_scope
        observed_digest, observation = historical_observation_resolver(
            approval.source_git_sha, migration.module_prefixes
        )
        if observed_digest != approval.source_digest:
            continue
        if observation.complexity != _expected_migration_complexity(
            baseline_scope.complexity, migration.delta
        ):
            continue
        if observation.import_projection_sha256 != migration.import_projection_sha256:
            continue
        if observation.owner_source_sha256 is None:
            continue
        validated[migration.migration_id] = observation
    return validated


def _effective_budget(
    budget: ArchitectureComplexityBudget,
    *,
    import_edge_pairs: Iterable[tuple[str, str]],
    source_index: RepositorySourceIndexPort | None,
    approved_observations: dict[str, ArchitectureMigrationObservation],
) -> ArchitectureComplexityBudget:
    pairs = tuple(import_edge_pairs)
    values = {field: getattr(budget.baseline.complexity, field) for field in _BUDGET_FIELDS}
    applicable: list[str] = []
    applied_scopes: list[tuple[str, ...]] = []
    for migration in budget.migrations:
        approved = approved_observations.get(migration.migration_id)
        if approved is None or source_index is None:
            continue
        if not migration.module_prefixes or migration.import_projection_sha256 is None:
            continue
        if import_projection_digest(pairs, migration.module_prefixes) != migration.import_projection_sha256:
            continue
        if source_scope_digest(source_index, migration.module_prefixes) != approved.owner_source_sha256:
            continue
        if any(_scopes_overlap(migration.module_prefixes, scope) for scope in applied_scopes):
            raise ArchitectureBudgetProvenanceError(
                "multiple approved architecture migrations overlap the same source scope"
            )
        applied_scopes.append(migration.module_prefixes)
        applicable.append(migration.migration_id)
        for field in _BUDGET_FIELDS:
            values[field] += getattr(migration.delta, field)
    negative = tuple(field for field, value in values.items() if value < 0)
    if negative:
        raise ArchitectureBudgetProvenanceError(
            "approved architecture migrations produce negative limits: " + ", ".join(negative)
        )
    return replace(
        budget,
        effective_limits=ArchitectureComplexity(**values),
        applicable_migration_ids=tuple(applicable),
    )


def _formal_scope_budget_violations(
    budget: ArchitectureComplexityBudget,
    evaluated: ArchitectureComplexityBudget,
    *,
    current: ArchitectureComplexity,
    import_edge_pairs: Iterable[tuple[str, str]],
    historical_observation_resolver: _HistoricalObservationResolver,
) -> tuple[ArchitectureBudgetViolation, ...]:
    pairs = tuple(import_edge_pairs)
    scopes: list[tuple[str, ...]] = []
    for migration in budget.migrations:
        if migration.module_prefixes and migration.module_prefixes not in scopes:
            scopes.append(migration.module_prefixes)
    registered_extension_scopes = _registered_extension_scopes()
    registered_extension_roots = {scope[0] for scope in registered_extension_scopes}
    extension_prefixes = {
        source.split(".", 1)[0]
        for source, _target in pairs
        if source.split(".", 1)[0] in registered_extension_roots
    }
    for extension_scope in registered_extension_scopes:
        if extension_scope[0] in extension_prefixes and extension_scope not in scopes:
            scopes.append(extension_scope)
    for index, left in enumerate(scopes):
        for right in scopes[index + 1:]:
            if _scopes_overlap(left, right):
                raise ArchitectureBudgetProvenanceError(
                    "architecture migration scopes overlap and cannot provide independent headroom"
                )

    migrations = {item.migration_id: item for item in budget.migrations}
    applicable_by_scope: dict[tuple[str, ...], ArchitectureMigrationAllowance] = {}
    for migration_id in evaluated.applicable_migration_ids:
        migration = migrations[migration_id]
        if migration.module_prefixes in applicable_by_scope:
            raise ArchitectureBudgetProvenanceError(
                "multiple applicable architecture migrations share one source scope"
            )
        applicable_by_scope[migration.module_prefixes] = migration

    baseline_parts: list[ArchitectureComplexity] = []
    current_parts: list[ArchitectureComplexity] = []
    violations: list[ArchitectureBudgetViolation] = []
    for scope in scopes:
        _baseline_digest, baseline_observation = historical_observation_resolver(
            budget.baseline.git_sha, scope
        )
        baseline_part = baseline_observation.complexity
        current_part = scoped_architecture_complexity(
            current, import_edge_pairs=pairs, module_prefixes=scope
        )
        baseline_parts.append(baseline_part)
        current_parts.append(current_part)
        migration = applicable_by_scope.get(scope)
        expected = (
            baseline_part
            if migration is None
            else _apply_complexity_delta(
                baseline_part, migration.delta,
                field=f"applicable migration {migration.migration_id}",
            )
        )
        scope_label = ",".join(scope)
        for field in _BUDGET_FIELDS:
            observed = getattr(current_part, field)
            limit = getattr(expected, field)
            if observed > limit:
                violations.append(ArchitectureBudgetViolation(
                    dimension=field,
                    observed=observed,
                    limit=limit,
                    detail=(
                        f"{field} scoped architecture budget exceeded: scope={scope_label} "
                        f"observed={observed} limit={limit} "
                        f"migration={(migration.migration_id if migration else 'none')}"
                    ),
                ))

    for field in _BUDGET_FIELDS[:-1]:
        baseline_total = sum(getattr(part, field) for part in baseline_parts)
        current_total = sum(getattr(part, field) for part in current_parts)
        if baseline_total != getattr(budget.baseline.complexity, field):
            raise ArchitectureBudgetProvenanceError(
                f"architecture migration scopes do not partition baseline {field} authority"
            )
        if current_total != getattr(current, field):
            raise ArchitectureBudgetProvenanceError(
                f"architecture migration scopes do not partition current {field} authority"
            )

    if len(pairs) == current.import_edges:
        baseline_imports = sum(part.import_edges for part in baseline_parts)
        current_imports = sum(part.import_edges for part in current_parts)
        if baseline_imports != budget.baseline.complexity.import_edges:
            raise ArchitectureBudgetProvenanceError(
                "architecture migration scopes do not partition baseline import-edge authority"
            )
        if current_imports != current.import_edges:
            raise ArchitectureBudgetProvenanceError(
                "architecture migration scopes do not partition current import-edge authority"
            )
    return tuple(violations)


def audit_architecture_complexity_budget(
    root: Path,
    *,
    import_edges: int,
    import_edge_pairs: Iterable[tuple[str, str]] = (),
    source_index: RepositorySourceIndexPort | None = None,
    approval_set: ArchitectureMigrationApprovalSet | None = None,
    historical_observation_resolver: _HistoricalObservationResolver | None = None,
    verify_provenance: bool | None = None,
    working_tree_reference: ArchitectureComplexity | None = None,
) -> tuple[
    ArchitectureComplexity,
    ArchitectureComplexityBudget | None,
    tuple[ArchitectureBudgetViolation, ...],
]:
    current = current_architecture_complexity(import_edges=import_edges)
    if source_index is not None:
        marker = "noetrium_platform/foundation/governance/architecture/report.py"
        if not any(blob.relative_path == marker for blob in source_index.documents(suffixes={".py"})):
            return current, None, ()
    budget = load_architecture_complexity_budget(root, source_index=source_index)
    formal = (
        source_index is not None and source_index.source_authority == "git"
        if verify_provenance is None
        else bool(verify_provenance)
    )
    approved: dict[str, ArchitectureMigrationObservation] = {}
    if formal:
        if source_index is None or source_index.source_authority != "git":
            raise ArchitectureBudgetProvenanceError(
                "formal architecture budget verification requires Git source authority"
            )
        approved = _validated_approval_observations(
            budget, approval_set, historical_observation_resolver
        )
    evaluated = _effective_budget(
        budget,
        import_edge_pairs=import_edge_pairs,
        source_index=source_index,
        approved_observations=approved,
    )
    if formal and working_tree_reference is not None:
        raise ArchitectureBudgetProvenanceError(
            "formal architecture verification cannot use a working-tree reference"
        )
    if not formal and working_tree_reference is not None:
        evaluated = replace(evaluated, effective_limits=working_tree_reference)
    if formal:
        if historical_observation_resolver is None:
            raise ArchitectureBudgetProvenanceError(
                "formal architecture budget verification requires historical Git observations"
            )
        violations = list(_formal_scope_budget_violations(
            budget,
            evaluated,
            current=current,
            import_edge_pairs=import_edge_pairs,
            historical_observation_resolver=historical_observation_resolver,
        ))
    else:
        violations = []
        for field in _BUDGET_FIELDS:
            observed = getattr(current, field)
            limit = getattr(evaluated.limits, field)
            if observed > limit:
                violations.append(ArchitectureBudgetViolation(
                    dimension=field,
                    observed=observed,
                    limit=limit,
                    detail=f"{field} complexity budget exceeded: observed={observed} limit={limit}",
                ))
    return current, evaluated, tuple(violations)


__all__ = [
    "ArchitectureBaselineAuthority",
    "ArchitectureBudgetProvenanceError",
    "ArchitectureBudgetViolation",
    "ArchitectureComplexity",
    "ArchitectureComplexityBudget",
    "ArchitectureMigrationAllowance",
    "ArchitectureMigrationApproval",
    "ArchitectureMigrationApprovalSet",
    "ArchitectureMigrationObservation",
    "audit_architecture_complexity_budget",
    "current_architecture_complexity",
    "import_projection_digest",
    "load_architecture_complexity_budget",
    "load_architecture_migration_approval_set",
    "scoped_architecture_complexity",
    "source_catalog_complexity",
    "source_scope_digest",
    "verify_architecture_baseline_authority",
]

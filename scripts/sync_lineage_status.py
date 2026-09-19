from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

LINEAGE_SCHEMA = "noetrium-research-lineage.v1"
REPRODUCTION_SCHEMA = "noetrium.reproduction.projection.v5"
STATUS_SCHEMA = "noetrium.lineage-reproduction-status.v2"
STATUS_AUTHORITY = "generated_from_lineage_graph_and_typed_reproduction_projections"
FORBIDDEN_NODE_FIELDS = frozenset(
    {
        "official_repo",
        "existing_noetrium_asset",
        "reproduction_status",
        "source_note",
        "reported_anchor",
        "package",
        "blockers",
    }
)


def _load(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reproduction_summary(document: Mapping[str, Any]) -> Mapping[str, Any]:
    identity = document.get("identity")
    catalog = document.get("catalog")
    if not isinstance(identity, Mapping) or not isinstance(catalog, Mapping):
        raise ValueError("reproduction projection requires identity and catalog objects")
    assets = document.get("assets", [])
    tests = document.get("scientific_tests", [])
    sources = document.get("source_lanes", [])
    if not isinstance(assets, list) or not isinstance(tests, list) or not isinstance(sources, list):
        raise ValueError("reproduction projection collections must be arrays")
    return {
        "package": document["package"],
        "package_digest": document["package_digest"],
        "lifecycle": document["lifecycle"],
        "benchmark_ids": catalog.get("benchmark_ids", []),
        "source_lanes": [
            {
                "lane_id": row["lane_id"],
                "kind": row["kind"],
                **(
                    {
                        "repository": row["repository"],
                        "commit": row.get("commit"),
                    }
                    if isinstance(row.get("repository"), str)
                    else {
                        "publication_uri": row["publication_uri"],
                        "venue": row.get("venue"),
                        "year": row.get("year"),
                        "publication_id": row.get("publication_id"),
                        "revision": row.get("revision"),
                        "content_sha256": row.get("content_sha256"),
                    }
                ),
            }
            for row in sources
        ],
        "assets": [
            {
                "kind": row["kind"],
                "path": row["path"],
                "content_sha256": row["content_sha256"],
            }
            for row in assets
        ],
        "blockers": document.get("blockers", []),
        "evidence_refs": document.get("evidence_refs", []),
        "reported_claim_count": len(document.get("reported_results", [])),
        "reference_baseline_count": len(document.get("reference_baselines", [])),
        "fidelity_delta_count": len(document.get("deltas", [])),
        "scientific_tests": [
            {
                "path": row["path"],
                "content_sha256": row["content_sha256"],
            }
            for row in tests
        ],
    }


def _reproductions_by_method(root: Path) -> dict[str, list[Mapping[str, Any]]]:
    by_method: dict[str, list[Mapping[str, Any]]] = {}
    for projection_path in sorted((root / "research/reproductions").glob("*/reproduction.json")):
        document = _load(projection_path)
        if document.get("schema") != REPRODUCTION_SCHEMA:
            raise ValueError(
                f"{projection_path.relative_to(root)} must use {REPRODUCTION_SCHEMA}"
            )
        identity = document.get("identity")
        if not isinstance(identity, Mapping):
            raise ValueError(f"{projection_path.relative_to(root)} requires identity")
        method_id = identity.get("method_id")
        if not isinstance(method_id, str) or not method_id:
            raise ValueError(f"{projection_path.relative_to(root)} requires identity.method_id")
        by_method.setdefault(method_id, []).append(_reproduction_summary(document))
    for rows in by_method.values():
        rows.sort(key=lambda row: str(row["package"]))
    return by_method


def _status_path(lineage_path: Path) -> Path:
    suffix = "_v1"
    stem = lineage_path.stem
    if not stem.endswith(suffix):
        raise ValueError(f"canonical lineage filename must end in {suffix}: {lineage_path}")
    return lineage_path.with_name(stem[: -len(suffix)] + "_status.json")


def project_lineage(
    root: Path,
    lineage_path: Path,
    reproductions: Mapping[str, list[Mapping[str, Any]]],
) -> tuple[Path, Mapping[str, Any]]:
    lineage = _load(lineage_path)
    if lineage.get("schema") != LINEAGE_SCHEMA:
        raise ValueError(f"{lineage_path.relative_to(root)} must use {LINEAGE_SCHEMA}")
    lineage_id = lineage.get("lineage_id")
    if not isinstance(lineage_id, str) or not lineage_id:
        raise ValueError(f"{lineage_path.relative_to(root)} requires lineage_id")
    nodes = lineage.get("core_nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError(f"{lineage_path.relative_to(root)} requires non-empty core_nodes")

    node_rows: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, Mapping):
            raise TypeError(f"core_nodes[{index}] must be an object")
        forbidden = sorted(FORBIDDEN_NODE_FIELDS.intersection(node))
        if forbidden:
            raise ValueError(
                f"core_nodes[{index}] duplicates reproduction authority fields: {forbidden}"
            )
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id:
            raise ValueError(f"core_nodes[{index}] requires id")
        if node_id in seen:
            raise ValueError(f"duplicate lineage node id: {node_id}")
        seen.add(node_id)
        node_rows.append(
            {
                "id": node_id,
                "reproductions": reproductions.get(node_id, []),
            }
        )

    body: dict[str, Any] = {
        "schema": STATUS_SCHEMA,
        "authority": STATUS_AUTHORITY,
        "lineage_id": lineage_id,
        "lineage_source_sha256": hashlib.sha256(lineage_path.read_bytes()).hexdigest(),
        "nodes": node_rows,
    }
    body["projection_digest"] = _digest(body)
    return _status_path(lineage_path), body


def project_all(root: Path) -> dict[Path, Mapping[str, Any]]:
    reproductions = _reproductions_by_method(root)
    outputs: dict[Path, Mapping[str, Any]] = {}
    for path in sorted((root / "research/catalog/lineages").glob("*_v1.json")):
        document = _load(path)
        if document.get("schema") != LINEAGE_SCHEMA:
            continue
        output, projected = project_lineage(root, path, reproductions)
        outputs[output] = projected
    return outputs


def sync(root: Path, *, check: bool) -> tuple[str, ...]:
    drift: list[str] = []
    outputs = project_all(root)
    for path, document in outputs.items():
        expected = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        actual = path.read_text(encoding="utf-8") if path.exists() else None
        if actual == expected:
            continue
        relative = str(path.relative_to(root))
        if check:
            drift.append(relative)
        else:
            path.write_text(expected, encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": STATUS_SCHEMA,
                "lineage_count": len(outputs),
                "drift_count": len(drift),
                "drift": drift,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return tuple(drift)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Project relationship-only lineage graphs over typed reproduction authorities."
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    drift = sync(args.root.resolve(), check=args.check)
    return 1 if drift else 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LINEAGE = ROOT / "research/catalog/lineages/deliberative_language_agent_search_v1.json"
STATUS = ROOT / "research/catalog/lineages/deliberative_language_agent_search_status.json"
FORBIDDEN_NODE_FIELDS = {
    "official_repo",
    "existing_noetrium_asset",
    "reproduction_status",
    "source_note",
    "reported_anchor",
    "package",
    "blockers",
}


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_curated_lineage_owns_relationships_not_reproduction_state() -> None:
    lineage = _load(LINEAGE)
    assert lineage["schema"] == "noetrium-research-lineage.v1"
    assert lineage["execution_mode"]["mode"] == "parallel_peer_reviewed_core_lanes"
    assert "first_execution_order" not in lineage
    assert [node["id"] for node in lineage["core_nodes"]] == [
        "react",
        "self-refine",
        "reflexion",
        "tree-of-thoughts",
        "rap",
        "lats",
        "qlass",
    ]
    for node in lineage["core_nodes"]:
        assert not FORBIDDEN_NODE_FIELDS.intersection(node)


def test_generated_lineage_status_is_content_bound_to_curated_graph() -> None:
    lineage = _load(LINEAGE)
    status = _load(STATUS)
    assert status["schema"] == "noetrium.lineage-reproduction-status.v2"
    assert status["authority"] == "generated_from_lineage_graph_and_typed_reproduction_projections"
    assert status["lineage_id"] == lineage["lineage_id"]
    assert status["lineage_source_sha256"] == hashlib.sha256(LINEAGE.read_bytes()).hexdigest()
    assert [row["id"] for row in status["nodes"]] == [
        row["id"] for row in lineage["core_nodes"]
    ]
    assert len(status["projection_digest"]) == 64


def test_lineage_status_reuses_typed_reproduction_projection_truth() -> None:
    status = _load(STATUS)
    mapped = 0
    for node in status["nodes"]:
        for projected in node["reproductions"]:
            mapped += 1
            reproduction_path = (
                ROOT
                / "research/reproductions"
                / projected["package"]
                / "reproduction.json"
            )
            reproduction = _load(reproduction_path)
            assert reproduction["identity"]["method_id"] == node["id"]
            assert projected["package_digest"] == reproduction["package_digest"]
            assert projected["lifecycle"] == reproduction["lifecycle"]
            assert projected["benchmark_ids"] == reproduction["catalog"]["benchmark_ids"]
            assert projected["blockers"] == reproduction["blockers"]
            assert projected["evidence_refs"] == reproduction["evidence_refs"]
            assert projected["reported_claim_count"] == len(reproduction["reported_results"])
            assert projected["reference_baseline_count"] == len(reproduction["reference_baselines"])
            assert projected["fidelity_delta_count"] == len(reproduction["deltas"])
            assert projected["source_lanes"] == [
                {
                    "lane_id": row["lane_id"],
                    "kind": row["kind"],
                    "repository": row["repository"],
                    "commit": row.get("commit"),
                }
                for row in reproduction["source_lanes"]
            ]
            assert projected["assets"] == [
                {
                    "kind": row["kind"],
                    "path": row["path"],
                    "content_sha256": row["content_sha256"],
                }
                for row in reproduction["assets"]
            ]
            assert projected["scientific_tests"] == reproduction["scientific_tests"]
    assert mapped == len(status["nodes"])
    assert all(len(node["reproductions"]) == 1 for node in status["nodes"])

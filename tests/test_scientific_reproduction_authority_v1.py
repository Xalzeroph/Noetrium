from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from research.reproductions.contracts import (
    ReportedResult,
    ReproductionAssetKind,
    ReproductionAssetRef,
    ReproductionCatalog,
    ReproductionDefinition,
    ReproductionEvidenceKind,
    ReproductionEvidenceQualification,
    ReproductionEvidenceRef,
    ReproductionMatchCriterion,
    ReproductionMatchCriterionStatus,
    ReproductionIdentity,
    ReproductionLifecycle,
)

ROOT = Path(__file__).resolve().parents[1]


def test_every_reproduction_has_typed_authorities_and_generated_projection() -> None:
    packages = tuple(sorted(path for path in (ROOT / "research/reproductions").iterdir() if path.is_dir()))
    packages = tuple(path for path in packages if (path / "reproduction.json").is_file())
    assert len(packages) >= 36
    for package in packages:
        assert (package / "definition.py").is_file()
        assert (package / "source.py").is_file()
        document = json.loads((package / "reproduction.json").read_text(encoding="utf-8"))
        assert document["schema"] == "noetrium.reproduction.projection.v9"
        assert document["authority"] == "generated_from_typed_definition_and_source"
        assert document["package"] == package.name
        assert "scientific_contract" not in document
        assert "reproduction_status" not in document["catalog"]
        assert document["assets"]
        for asset in document["assets"]:
            assert set(asset) == {"kind", "path", "declaration_digest", "content_sha256"}
            payload = (ROOT / asset["path"]).read_bytes()
            assert asset["content_sha256"] == hashlib.sha256(payload).hexdigest()
        assert document["scientific_tests"]
        for scientific_test in document["scientific_tests"]:
            assert set(scientific_test) == {"path", "content_sha256"}
            payload = (ROOT / scientific_test["path"]).read_bytes()
            assert scientific_test["content_sha256"] == hashlib.sha256(payload).hexdigest()
        assert document["package_digest"] == canonical_digest(
            {
                "definition_digest": document["definition_digest"],
                "source_registry_digest": document["source_registry_digest"],
                "assets": document["assets"],
                "scientific_tests": document["scientific_tests"],
                "research_os": document["research_os"],
            }
        )


def test_artifact_only_reproduction_never_invents_executable_source() -> None:
    mars = json.loads(
        (ROOT / "research/reproductions/mars_automated_ai_research/reproduction.json")
        .read_text(encoding="utf-8")
    )
    assert mars["lifecycle"] == "artifact_only"
    executable = {"official_executable", "later_released_executable", "surrogate", "independent"}
    assert all(row["kind"] not in executable for row in mars["source_lanes"])



def _matched_evidence(*claim_ids: str) -> ReproductionEvidenceRef:
    run_manifest_digest = canonical_digest({"run": "fixture"})
    evidence_bundle_digest = canonical_digest({"bundle": "fixture"})
    claims = tuple(claim_ids)
    qualification = ReproductionEvidenceQualification(
        qualification_id="matched-fixture-qualification",
        decision=ReproductionEvidenceKind.MATCHED_RESULT,
        run_id="run-fixture",
        run_manifest_digest=run_manifest_digest,
        evidence_bundle_digest=evidence_bundle_digest,
        claim_ids=claims,
        criteria=(
            ReproductionMatchCriterion(
                criterion_id="benchmark-cut",
                status=ReproductionMatchCriterionStatus.SATISFIED,
                authority_digest=canonical_digest(
                    {"benchmark": "fixture-bench"}
                ),
                detail="Exact benchmark cut is content-addressed.",
            ),
            ReproductionMatchCriterion(
                criterion_id="method-semantics",
                status=ReproductionMatchCriterionStatus.SATISFIED,
                authority_digest=canonical_digest(
                    {"method": "fixture-method"}
                ),
                detail="Method semantics match the declared reproduction.",
            ),
            ReproductionMatchCriterion(
                criterion_id="model-identity",
                status=ReproductionMatchCriterionStatus.NOT_APPLICABLE,
                authority_digest=canonical_digest(
                    {"model": "not-applicable"}
                ),
                detail="Fixture claim has no model dependency.",
            ),
            ReproductionMatchCriterion(
                criterion_id="environment",
                status=ReproductionMatchCriterionStatus.NOT_APPLICABLE,
                authority_digest=canonical_digest(
                    {"environment": "not-applicable"}
                ),
                detail="Fixture claim has no external environment dependency.",
            ),
            ReproductionMatchCriterion(
                criterion_id="evaluation-protocol",
                status=ReproductionMatchCriterionStatus.SATISFIED,
                authority_digest=canonical_digest(
                    {"evaluation": "fixture-evaluator"}
                ),
                detail="Evaluation protocol is content-addressed.",
            ),
        ),
    )
    return ReproductionEvidenceRef(
        evidence_id="matched-fixture",
        kind=ReproductionEvidenceKind.MATCHED_RESULT,
        run_id="run-fixture",
        run_manifest_digest=run_manifest_digest,
        bundle_id="bundle-fixture",
        evidence_bundle_digest=evidence_bundle_digest,
        manifest_ref="evidence/bundle-fixture/manifest.json",
        manifest_sha256=canonical_digest({"manifest": "fixture"}),
        claim_ids=claims,
        qualification=qualification,
    )


def _matched_definition(
    *,
    evidence_refs: tuple[ReproductionEvidenceRef, ...],
) -> ReproductionDefinition:
    return ReproductionDefinition(
        package="evidence-fixture",
        lifecycle=ReproductionLifecycle.MATCHED_REPRODUCTION,
        identity=ReproductionIdentity(
            method_id="evidence-fixture",
            title="Evidence Fixture",
            paper_uri="https://example.test/evidence-fixture",
            year=2026,
        ),
        catalog=ReproductionCatalog(
            domains=("test",),
            families=("evidence",),
            priority=1,
            benchmark_ids=("fixture-bench",),
            platform_pressure=("experimentation/run",),
            method_owned=("fixture semantics",),
            platform_owned=("evidence authority",),
        ),
        assets=(
            ReproductionAssetRef(
                ReproductionAssetKind.METHOD_PROGRAM,
                "research/reproductions/evidence_fixture/program.py",
            ),
        ),
        reported_results=(
            ReportedResult(
                claim_id="fixture_claim",
                metric_id="task_success_percent",
                value=100.0,
            ),
        ),
        evidence_refs=evidence_refs,
        scientific_tests=("tests/test_scientific_fixture.py",),
    )


def test_matched_reproduction_requires_typed_bundle_evidence() -> None:
    with pytest.raises(
        ValueError,
        match="requires matched-result evidence",
    ):
        _matched_definition(evidence_refs=())

    evidence = _matched_evidence("fixture_claim")
    definition = _matched_definition(evidence_refs=(evidence,))
    assert definition.lifecycle is ReproductionLifecycle.MATCHED_REPRODUCTION
    assert definition.evidence_refs == (evidence,)


def test_matched_evidence_cannot_claim_unknown_result() -> None:
    evidence = _matched_evidence("unknown_claim")
    with pytest.raises(ValueError, match="unknown claims"):
        _matched_definition(evidence_refs=(evidence,))



def test_matched_evidence_requires_independent_qualification() -> None:
    with pytest.raises(ValueError, match="typed qualification"):
        ReproductionEvidenceRef(
            evidence_id="unqualified-match",
            kind=ReproductionEvidenceKind.MATCHED_RESULT,
            run_id="run-fixture",
            run_manifest_digest=canonical_digest({"run": "fixture"}),
            bundle_id="bundle-fixture",
            evidence_bundle_digest=canonical_digest({"bundle": "fixture"}),
            manifest_ref="evidence/bundle-fixture/manifest.json",
            manifest_sha256=canonical_digest({"manifest": "fixture"}),
            claim_ids=("fixture_claim",),
        )


def test_matched_qualification_rejects_unresolved_criterion() -> None:
    with pytest.raises(ValueError, match="unresolved criteria"):
        ReproductionEvidenceQualification(
            qualification_id="unresolved-match",
            decision=ReproductionEvidenceKind.MATCHED_RESULT,
            run_id="run-fixture",
            run_manifest_digest=canonical_digest({"run": "fixture"}),
            evidence_bundle_digest=canonical_digest({"bundle": "fixture"}),
            claim_ids=("fixture_claim",),
            criteria=(
                ReproductionMatchCriterion(
                    criterion_id="benchmark-cut",
                    status=ReproductionMatchCriterionStatus.SATISFIED,
                    authority_digest=canonical_digest({"benchmark": "fixture"}),
                    detail="Benchmark is frozen.",
                ),
                ReproductionMatchCriterion(
                    criterion_id="method-semantics",
                    status=ReproductionMatchCriterionStatus.SATISFIED,
                    authority_digest=canonical_digest({"method": "fixture"}),
                    detail="Method is frozen.",
                ),
                ReproductionMatchCriterion(
                    criterion_id="model-identity",
                    status=ReproductionMatchCriterionStatus.UNRESOLVED,
                    authority_digest=canonical_digest(
                        {"model": "unresolved"}
                    ),
                    detail="Historical model service identity is unresolved.",
                ),
                ReproductionMatchCriterion(
                    criterion_id="environment",
                    status=ReproductionMatchCriterionStatus.NOT_APPLICABLE,
                    authority_digest=canonical_digest({"environment": "na"}),
                    detail="No external environment.",
                ),
                ReproductionMatchCriterion(
                    criterion_id="evaluation-protocol",
                    status=ReproductionMatchCriterionStatus.SATISFIED,
                    authority_digest=canonical_digest({"evaluation": "fixture"}),
                    detail="Evaluator is frozen.",
                ),
            ),
        )


def test_evidence_qualification_must_bind_same_bundle() -> None:
    run_manifest_digest = canonical_digest({"run": "fixture"})
    qualification = ReproductionEvidenceQualification(
        qualification_id="pilot-qualification",
        decision=ReproductionEvidenceKind.PILOT,
        run_id="run-fixture",
        run_manifest_digest=run_manifest_digest,
        evidence_bundle_digest=canonical_digest({"bundle": "other"}),
        claim_ids=(),
        criteria=(
            ReproductionMatchCriterion(
                criterion_id="model-identity",
                status=ReproductionMatchCriterionStatus.UNRESOLVED,
                authority_digest=canonical_digest(
                    {"model": "pilot-substitution"}
                ),
                detail="Pilot uses a substitute model.",
            ),
        ),
    )
    with pytest.raises(ValueError, match="bundle drifted"):
        ReproductionEvidenceRef(
            evidence_id="pilot-fixture",
            kind=ReproductionEvidenceKind.PILOT,
            run_id="run-fixture",
            run_manifest_digest=run_manifest_digest,
            bundle_id="bundle-fixture",
            evidence_bundle_digest=canonical_digest({"bundle": "fixture"}),
            manifest_ref="evidence/bundle-fixture/manifest.json",
            manifest_sha256=canonical_digest({"manifest": "fixture"}),
            qualification=qualification,
        )



def test_matched_qualification_requires_full_scientific_closure() -> None:
    with pytest.raises(ValueError, match="missing required criteria"):
        ReproductionEvidenceQualification(
            qualification_id="partial-match",
            decision=ReproductionEvidenceKind.MATCHED_RESULT,
            run_id="run-fixture",
            run_manifest_digest=canonical_digest({"run": "fixture"}),
            evidence_bundle_digest=canonical_digest({"bundle": "fixture"}),
            claim_ids=("fixture_claim",),
            criteria=(
                ReproductionMatchCriterion(
                    criterion_id="benchmark-cut",
                    status=ReproductionMatchCriterionStatus.SATISFIED,
                    authority_digest=canonical_digest({"benchmark": "fixture"}),
                    detail="Only benchmark identity was checked.",
                ),
            ),
        )

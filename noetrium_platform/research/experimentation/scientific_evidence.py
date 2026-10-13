from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.truth import TruthModality, modal_attributes, truth_modality
from noetrium_platform.foundation.kernel.structure import (
    NoetriumUnit,
    atom_unit,
    endpoint_child_id,
    endpoint_unit,
    relation_id,
    relation_unit,
    structure_unit,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.contracts import (
    StudyMatrixExecutionReport,
    study_assignment_digest,
)


_EVIDENCE_TRAIT = "scientific-evidence"
_EVIDENCE_NODE_TYPE_PREFIX = "scientific-evidence."


def _evidence_node(
    node_id: str,
    kind: str,
    semantic_digest: str,
) -> NoetriumUnit:
    if len(semantic_digest) != 64 or any(
        ch not in "0123456789abcdef" for ch in semantic_digest
    ):
        raise ValueError(
            "scientific evidence semantic_digest must be lowercase SHA-256"
        )
    return atom_unit(
        node_id,
        f"{_EVIDENCE_NODE_TYPE_PREFIX}{kind}",
        {"semantic_digest": semantic_digest},
    )


def _evidence_relation(
    source: str,
    relation: str,
    target: str,
) -> NoetriumUnit:
    return relation_unit(
        (endpoint_unit(source, None, side="source"),),
        (endpoint_unit(target, None, side="target"),),
        relation,
    )


def scientific_evidence_graph(
    report: StudyMatrixExecutionReport,
) -> NoetriumUnit:
    """Compile one study report into the canonical Unit topology."""

    if type(report) is not StudyMatrixExecutionReport:
        raise TypeError(
            "scientific evidence graph requires StudyMatrixExecutionReport"
        )

    report_digest = canonical_digest(
        {
            "protocol_digest": report.protocol_digest,
            "binding_digest": report.binding_digest,
            "plan_digest": report.plan_digest,
            "observations": tuple(
                row.observation_digest for row in report.observations
            ),
            "aggregates": report.aggregates,
        }
    )
    root_id = f"study-report:{report_digest}"
    nodes: dict[str, NoetriumUnit] = {
        root_id: _evidence_node(root_id, "study_report", report_digest),
    }
    relations: list[NoetriumUnit] = []

    def link(
        source: str,
        relation: str,
        target: str,
        kind: str,
        digest: str,
    ) -> None:
        nodes[target] = _evidence_node(target, kind, digest)
        relations.append(_evidence_relation(source, relation, target))

    for kind, digest, relation in (
        ("protocol", report.protocol_digest, "uses_protocol"),
        ("binding", report.binding_digest, "uses_binding"),
        ("plan", report.plan_digest, "uses_plan"),
    ):
        link(
            root_id,
            relation,
            f"{kind}:{digest}",
            kind,
            digest,
        )

    for observation in report.observations:
        observation_id = f"observation:{observation.observation_digest}"
        link(
            root_id,
            "contains_observation",
            observation_id,
            "metric_observation",
            observation.observation_digest,
        )

        assignment_digest = study_assignment_digest(observation.assignment)
        link(
            observation_id,
            "observes_assignment",
            f"assignment:{assignment_digest}",
            "assignment",
            assignment_digest,
        )

        for kind, digest, relation in (
            (
                "trial_request",
                observation.trial_request_digest,
                "derived_from_request",
            ),
            (
                "trial_receipt",
                observation.trial_receipt_digest,
                "supported_by_receipt",
            ),
            (
                "verifier_receipt",
                observation.verifier_receipt_digest,
                "verified_by",
            ),
        ):
            if digest is None:
                continue
            link(
                observation_id,
                relation,
                f"{kind}:{digest}",
                kind,
                digest,
            )

        for digest in observation.measurement_record_digests:
            link(
                observation_id,
                "supported_by_measurement",
                f"measurement:{digest}",
                "measurement",
                digest,
            )

        references = (
            ()
            if observation.trial_receipt_reference is None
            else (
                (
                    "references_trial_receipt_artifact",
                    observation.trial_receipt_reference,
                ),
            )
        ) + tuple(
            ("references_evidence", ref)
            for ref in observation.evidence_refs
        )
        for relation, ref in references:
            digest = canonical_digest(ref)
            link(
                observation_id,
                relation,
                f"artifact-reference:{ref.reference_id}",
                "artifact_reference",
                digest,
            )

    for aggregate in report.aggregates:
        digest = canonical_digest(aggregate)
        link(
            root_id,
            "contains_aggregate",
            f"aggregate:{digest}",
            "metric_aggregate",
            digest,
        )

    return NoetriumUnit(
        f"scientific-evidence:{report_digest}",
        schemas=(_EVIDENCE_TRAIT,),
        attributes=modal_attributes(
            TruthModality.EVIDENCED,
            {
                "kind": "scientific-evidence",
                "parameters": {"root_id": root_id},
            },
        ),
        roles=(
            ("member", tuple(sorted(nodes.values(), key=lambda row: row.unit_id))),
            (
                "relation",
                tuple(sorted(relations, key=lambda row: row.semantic_digest)),
            ),
        ),
    )


def scientific_evidence_payload(
    evidence: NoetriumUnit,
) -> dict[str, object]:
    """Stable JSON projection of a scientific-evidence Unit."""

    if (
        type(evidence) is not NoetriumUnit
        or not evidence.has_trait(_EVIDENCE_TRAIT)
        or truth_modality(evidence) is not TruthModality.EVIDENCED
    ):
        raise TypeError(
            "scientific evidence payload requires scientific-evidence Unit"
        )
    nodes = tuple(
        {
            "node_id": node.unit_id,
            "kind": str(node.attribute("type_id")).removeprefix(
                _EVIDENCE_NODE_TYPE_PREFIX
            ),
            "semantic_digest": node.attribute("value")[
                "semantic_digest"
            ],
        }
        for node in evidence.units("member")
    )
    edges = tuple(
        {
            "source": endpoint_child_id(row.one_unit("source")),
            "relation": relation_id(row),
            "target": endpoint_child_id(row.one_unit("target")),
        }
        for row in evidence.units("relation")
    )
    return {
        "schema": "noetrium.scientific-evidence-unit.v2",
        "root_id": evidence.parameters["root_id"],
        "graph_digest": evidence.semantic_digest,
        "nodes": nodes,
        "edges": edges,
    }


__all__ = [
    "scientific_evidence_graph",
    "scientific_evidence_payload",
]

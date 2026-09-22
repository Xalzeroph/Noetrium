from __future__ import annotations

from argparse import Namespace
from dataclasses import asdict

from noetrium_platform.infrastructure.reliability.diagnostics.api import DiagnosticEvidencePort
from noetrium_platform.composition.diagnostic_io import (
    build_causal_graph,
    build_debug_snapshot,
    build_diagnostic_status,
    build_triage_plan,
    diagnose_failure,
    diagnostic_last_writer,
    diagnostic_timeline,
    inspect_diagnostic_index,
    locate_diagnostic_object,
    open_diagnostic_evidence,
    publish_crash_bundle,
    rebuild_diagnostic_index,
    verify_diagnostic_evidence,
)


def _index_status(args: Namespace):
    return inspect_diagnostic_index(args.root)


def _rebuild_index(args: Namespace):
    return rebuild_diagnostic_index(args.root)


def _crash_bundle(args: Namespace):
    return publish_crash_bundle(args.root, args.failure_id, args.output)


def _verify_evidence(evidence: DiagnosticEvidencePort, args: Namespace):
    return verify_diagnostic_evidence(evidence)


def _status(evidence: DiagnosticEvidencePort, args: Namespace):
    return build_diagnostic_status(
        evidence,
        model_state=args.model_state,
        study_state=args.study_state,
    ).to_dict()


def _locate(evidence: DiagnosticEvidencePort, args: Namespace):
    return locate_diagnostic_object(evidence, args.object_id)


def _why(evidence: DiagnosticEvidencePort, args: Namespace):
    result = diagnose_failure(evidence, args.failure_id)
    return result if not args.graph else {
        "diagnosis": asdict(result),
        "causal_graph": asdict(build_causal_graph(evidence, args.failure_id)),
    }


def _graph(evidence: DiagnosticEvidencePort, args: Namespace):
    return build_causal_graph(evidence, args.object_id, related_limit=args.limit)


def _timeline(evidence: DiagnosticEvidencePort, args: Namespace):
    return diagnostic_timeline(evidence, args.object_id, seconds=args.seconds)


def _last_writer(evidence: DiagnosticEvidencePort, args: Namespace):
    return diagnostic_last_writer(evidence, args.run_id, args.state_name)


def _unclosed_operations(evidence: DiagnosticEvidencePort, args: Namespace):
    return tuple(
        record.to_summary()
        for record in evidence.unclosed_operations(run_id=args.run_id, limit=args.limit)
    )


def _debug_snapshot(evidence: DiagnosticEvidencePort, args: Namespace):
    return build_debug_snapshot(
        evidence,
        args.object_id,
        seconds=args.seconds,
        telemetry_db=args.telemetry_db,
        metric_limit=args.metric_limit,
    )


def _triage_plan(evidence: DiagnosticEvidencePort, args: Namespace):
    return build_triage_plan(evidence, args.failure_id)


_DIRECT_ROUTES = {
    "index-status": _index_status,
    "rebuild-index": _rebuild_index,
    "crash-bundle": _crash_bundle,
}
_EVIDENCE_ROUTES = {
    "verify-evidence": _verify_evidence,
    "status": _status,
    "locate": _locate,
    "why": _why,
    "graph": _graph,
    "timeline": _timeline,
    "last-writer": _last_writer,
    "unclosed-operations": _unclosed_operations,
    "debug-snapshot": _debug_snapshot,
    "triage-plan": _triage_plan,
}


def route_diagnostics(args: Namespace):
    """Route diagnostic commands without command-count-dependent branch scanning.

    Algorithm-Complexity: O(1)
    Algorithm-Rationale: Hash-map lookup selects one direct or evidence handler regardless of the number of registered diagnostic commands.
    """

    command = getattr(args, "command", None)
    direct_handler = _DIRECT_ROUTES.get(command)
    if direct_handler is not None:
        return direct_handler(args)
    evidence_handler = _EVIDENCE_ROUTES.get(command)
    if evidence_handler is None:
        return None
    with open_diagnostic_evidence(args.root) as evidence:
        return evidence_handler(evidence, args)


__all__ = ["route_diagnostics"]

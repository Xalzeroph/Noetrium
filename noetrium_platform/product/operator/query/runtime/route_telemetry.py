from __future__ import annotations

from noetrium_platform.composition.diagnostic_io import query_metrics, summarize_metrics


def route_telemetry(args: object):
    command = getattr(args, "command", None)
    if command == "telemetry-query":
        return query_metrics(
            args.db,
            run_id=args.run_id,
            metric=args.metric,
            decision_cycle_id=args.decision_cycle_id,
            limit=args.limit,
        )
    if command == "telemetry-summary":
        return summarize_metrics(args.db, run_id=args.run_id, metric=args.metric)
    return None


__all__ = ["route_telemetry"]

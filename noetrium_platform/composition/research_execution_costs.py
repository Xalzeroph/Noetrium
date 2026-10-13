from __future__ import annotations

from noetrium_platform.evidence.observability.api import (
    ContextMetricObservation,
    ContextMetricSink,
    EventSink,
    event_record,
)
from noetrium_platform.foundation.kernel.kernel import (
    ComplexityContract,
    CostObservationSinkPort,
    RuntimeCostObservation,
    ExecutionContext,
)


class ForensicTelemetryCostObservationSink(CostObservationSinkPort):
    """Project one measured cost fact to the existing forensic + telemetry planes."""

    def __init__(
        self,
        events: EventSink,
        metrics: ContextMetricSink,
    ) -> None:
        if not isinstance(events, EventSink):
            raise TypeError("execution cost sink requires EventSink")
        if not isinstance(metrics, ContextMetricSink):
            raise TypeError("execution cost sink requires ContextMetricSink")
        self._events = events
        self._metrics = metrics

    def observe(
        self,
        context: ExecutionContext,
        observation: RuntimeCostObservation,
        *,
        contract: ComplexityContract | None = None,
    ) -> str:
        if not isinstance(context, ExecutionContext):
            raise TypeError("execution cost observation requires ExecutionContext")
        if type(observation) is not RuntimeCostObservation:
            raise TypeError("execution cost observation must be typed")
        coordinate = context.graph_coordinate
        if coordinate is None:
            raise ValueError("execution cost observation requires graph coordinate")
        if coordinate.coordinate_digest != observation.coordinate_digest:
            raise ValueError("execution cost observation coordinate drift")
        if contract is not None:
            if type(contract) is not ComplexityContract:
                raise TypeError("execution cost contract must be typed")
            if observation.contract_digest != contract.contract_digest:
                raise ValueError("execution cost observation/contract digest drift")

        event_id = f"execution_cost_{observation.observation_digest}"
        self._events.append_event(
            event_record(
                event_id=event_id,
                event_type="EXECUTION_COST_OBSERVED",
                context=context,
                component_id=observation.algorithm_id,
                payload={
                    "observation": observation.as_payload(),
                    "complexity_contract": (
                        None if contract is None else contract.as_payload()
                    ),
                },
                request_refs=(observation.observation_digest,),
            )
        )

        algorithm = observation.algorithm_id
        metrics: list[ContextMetricObservation] = [
            ContextMetricObservation(
                "execution.cost.wall",
                observation.wall_ns / 1_000_000_000.0,
                (("algorithm", algorithm), ("outcome", observation.outcome)),
            ),
            ContextMetricObservation(
                "execution.cost.cpu",
                observation.cpu_ns / 1_000_000_000.0,
                (("algorithm", algorithm), ("outcome", observation.outcome)),
            ),
        ]
        for kind, value in (
            ("start", observation.rss_start_bytes),
            ("end", observation.rss_end_bytes),
            ("process_peak", observation.rss_peak_process_bytes),
        ):
            if value is not None:
                metrics.append(
                    ContextMetricObservation(
                        "execution.cost.rss",
                        float(value),
                        (("algorithm", algorithm), ("kind", kind)),
                    )
                )
        metrics.extend(
            ContextMetricObservation(
                "execution.cost.scale",
                float(value),
                (("algorithm", algorithm), ("variable", name)),
            )
            for name, value in observation.scale_values
        )
        metrics.extend(
            ContextMetricObservation(
                "execution.cost.work",
                float(value),
                (("algorithm", algorithm), ("counter", name)),
            )
            for name, value in observation.work_counters
        )
        metrics.extend(
            ContextMetricObservation(
                "execution.cost.stage",
                value / 1_000_000_000.0,
                (("algorithm", algorithm), ("kind", name)),
            )
            for name, value in observation.time_ns
        )
        metrics.extend(
            ContextMetricObservation(
                "execution.cost.wait",
                value / 1_000_000_000.0,
                (("algorithm", algorithm), ("kind", name)),
            )
            for name, value in observation.wait_ns
        )
        metrics.extend(
            ContextMetricObservation(
                "execution.cost.io",
                float(value),
                (("algorithm", algorithm), ("kind", name)),
            )
            for name, value in observation.io_bytes
        )
        metrics.extend(
            ContextMetricObservation(
                "execution.cost.memory",
                float(value),
                (("algorithm", algorithm), ("kind", name)),
            )
            for name, value in observation.memory_bytes
        )
        if observation.average_parallelism is not None:
            metrics.append(
                ContextMetricObservation(
                    "execution.cost.parallelism",
                    observation.average_parallelism,
                    (("algorithm", algorithm),),
                )
            )
        if contract is not None:
            scales = dict(observation.scale_values)
            required = set(contract.time_upper_bound.variables)
            if required <= scales.keys():
                growth = contract.time_upper_bound.growth_proxy(scales)
                metrics.append(
                    ContextMetricObservation(
                        "execution.cost.time_bound_growth",
                        growth,
                        (("algorithm", algorithm), ("bound", "upper")),
                    )
                )
                for clock, cost_ns in (
                    ("wall", observation.wall_ns),
                    ("cpu", observation.cpu_ns),
                ):
                    metrics.append(
                        ContextMetricObservation(
                            "execution.cost.time_bound_normalized",
                            contract.time_upper_bound.normalize_cost(
                                cost_ns / 1_000_000_000.0,
                                scales,
                            ),
                            (
                                ("algorithm", algorithm),
                                ("bound", "upper"),
                                ("clock", clock),
                            ),
                        )
                    )
        self._metrics.observe_many(context, tuple(metrics))
        return event_id


__all__ = ["ForensicTelemetryCostObservationSink"]

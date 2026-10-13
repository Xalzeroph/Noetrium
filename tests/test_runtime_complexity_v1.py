from __future__ import annotations

from threading import Thread
import time

from noetrium_platform.composition.research_execution_costs import (
    ForensicTelemetryCostObservationSink,
)
from noetrium_platform.foundation.kernel.kernel import (
    ComplexityBound,
    ComplexityContract,
    ComplexityFactor,
    ComplexityMonomial,
    RuntimeCostScope,
    add_cost_wait_ns,
    add_cost_work,
    set_cost_scale,
    set_cost_work_span,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    GraphExecutionCoordinate,
    execution_context_scope,
)
from tests._concurrency_support import OwnedForensicStore


class _MetricCapture:
    def __init__(self) -> None:
        self.rows = []

    def observe_many(self, context, observations):
        self.rows.extend((context, row) for row in observations)
        return tuple(range(1, len(observations) + 1))

    def observe(self, context, name, value, **dimensions):
        self.rows.append((context, (name, value, dimensions)))
        return len(self.rows)


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="a" * 64,
        trace_id="trace",
        span_id="span",
        task_id="attempt-1",
        graph_coordinate=GraphExecutionCoordinate(
            research_revision_digest="b" * 64,
            execution_id="execution-1",
            cut_id="c" * 64,
            graph_path=("root", "node"),
            graph_node_id="root::node",
            attempt_id="attempt-1",
            generation=2,
        ),
    )


def test_complexity_contract_is_canonical_and_typed() -> None:
    bound = ComplexityBound(
        (
            ComplexityMonomial(
                (
                    ComplexityFactor("edges"),
                    ComplexityFactor("vertices"),
                )
            ),
        )
    )
    contract = ComplexityContract(
        "graph.scan",
        "d" * 64,
        bound,
        ComplexityBound.linear("vertices"),
        ("sparse adjacency index",),
    )
    assert contract.time_upper_bound.terms[0].factors[0].variable == "edges"
    assert len(contract.contract_digest) == 64


def test_runtime_cost_scope_records_failure_and_thread_safe_work_span() -> None:
    context = _context()
    scope = RuntimeCostScope(
        context,
        algorithm_id="graph.attempt",
        implementation_digest="d" * 64,
    )
    try:
        with execution_context_scope(context), scope:
            set_cost_scale("trials", 70)

            def worker() -> None:
                for _ in range(1000):
                    scope.add_work("leaf_steps", 1)
                scope.add_wait_ns("lock", 100)

            threads = tuple(Thread(target=worker) for _ in range(4))
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            set_cost_work_span(work_ns=4000, critical_span_ns=1000)
            raise RuntimeError("expected")
    except RuntimeError:
        pass

    observation = scope.observation
    assert observation is not None
    assert observation.outcome == "failed"
    assert dict(observation.scale_values)["trials"] == 70
    assert dict(observation.work_counters)["leaf_steps"] == 4000
    assert dict(observation.wait_ns)["lock"] == 400
    assert observation.average_parallelism == 4.0
    assert observation.rss_peak_process_bytes is None or (
        observation.rss_start_bytes is None
        or observation.rss_peak_process_bytes >= observation.rss_start_bytes
    )


def test_cost_observation_projects_to_graph_forensics_and_metrics(tmp_path) -> None:
    context = _context()
    scope = RuntimeCostScope(
        context,
        algorithm_id="research.execution.node.attempt.total",
        implementation_digest="e" * 64,
    )
    with execution_context_scope(context), scope:
        set_cost_scale("input_count", 2)
        add_cost_work("actions", 3)
        time.sleep(0.001)

    observation = scope.observation
    assert observation is not None
    store = OwnedForensicStore(tmp_path / "forensics")
    metrics = _MetricCapture()
    try:
        sink = ForensicTelemetryCostObservationSink(store, metrics)
        event_id = sink.observe(context, observation)
        store.flush_projections()

        record = store.index.locate(event_id)
        assert record is not None
        assert record.graph_node_id == "root::node"
        assert record.graph_attempt_id == "attempt-1"
        payload = record.to_payload()
        assert payload["event_type"] == "EXECUTION_COST_OBSERVED"
        assert payload["payload"]["observation"]["observation_digest"] == (
            observation.observation_digest
        )

        names = {
            row.name
            for _, row in metrics.rows
            if hasattr(row, "name")
        }
        assert {
            "execution.cost.wall",
            "execution.cost.cpu",
            "execution.cost.scale",
            "execution.cost.work",
        } <= names
    finally:
        store.close()


def test_complexity_bound_growth_proxy_normalizes_across_scale() -> None:
    linear = ComplexityBound.linear("n")
    nlogn = ComplexityBound(
        (
            ComplexityMonomial(
                (ComplexityFactor("n", log_power=1),)
            ),
        )
    )
    assert abs(linear.growth_proxy({"n": 10}) - 10.0) < 1e-12
    assert abs(linear.normalize_cost(100.0, {"n": 10}) - 10.0) < 1e-12
    assert nlogn.growth_proxy({"n": 1}) > 0.0
    try:
        linear.growth_proxy({})
    except KeyError as exc:
        assert "n" in str(exc)
    else:
        raise AssertionError("missing complexity scale must fail closed")


def test_cost_sink_emits_bound_normalized_time_metrics(tmp_path) -> None:
    context = _context()
    contract = ComplexityContract(
        "graph.linear",
        "f" * 64,
        ComplexityBound.linear("items"),
        ComplexityBound.linear("items"),
        ("items is the complete scanned input",),
        time_lower_bound=ComplexityBound.linear("items"),
    )
    scope = RuntimeCostScope(
        context,
        algorithm_id=contract.algorithm_id,
        contract=contract,
    )
    with execution_context_scope(context), scope:
        set_cost_scale("items", 4)
        add_cost_work("items_examined", 4)

    observation = scope.observation
    assert observation is not None
    store = OwnedForensicStore(tmp_path / "normalized-forensics")
    metrics = _MetricCapture()
    try:
        sink = ForensicTelemetryCostObservationSink(store, metrics)
        sink.observe(context, observation, contract=contract)
        rows = [
            row for _, row in metrics.rows
            if hasattr(row, "name")
        ]
        growth = next(
            row for row in rows
            if row.name == "execution.cost.time_bound_growth"
        )
        normalized = [
            row for row in rows
            if row.name == "execution.cost.time_bound_normalized"
        ]
        assert growth.value == 4.0
        assert len(normalized) == 2
        assert all(row.value >= 0.0 for row in normalized)
    finally:
        store.close()

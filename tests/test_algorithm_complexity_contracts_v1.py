from noetrium_platform.capabilities.model.deployment.composition.replica_pool import (
    MODEL_WARM_DOMINANCE_COMPLEXITY,
)
from noetrium_platform.capabilities.model.serving.endpoint.runtime.selection_policy import (
    MODEL_REPLICA_ROUTING_COMPLEXITY,
)
from noetrium_platform.composition.research_graph_frontier import (
    RESEARCH_GRAPH_FRONTIER_COMPLEXITY,
)
from noetrium_platform.composition.research_execution_graph import (
    RESEARCH_EXECUTION_DESCENDANTS_COMPLEXITY,
    RESEARCH_EXECUTION_SEMANTIC_PROPAGATION_COMPLEXITY,
    RESEARCH_EXECUTION_TOPOLOGY_COMPLEXITY,
)
from noetrium_platform.infrastructure.resources.authority.runtime.authority import (
    RESOURCE_CLAIM_ADMISSION_COMPLEXITY,
    RESOURCE_PHYSICAL_BINDING_LOOKUP_COMPLEXITY,
    RESOURCE_SNAPSHOT_FILTER_MATERIALIZATION_COMPLEXITY,
)
from noetrium_platform.infrastructure.resources.authority.runtime.reconciliation import (
    RESOURCE_AFFECTED_RECONCILIATION_COMPLEXITY,
)
from noetrium_platform.research.execution.graph.api.contracts import (
    EXECUTION_GRAPH_INDEX_COMPLEXITY,
    SELECTED_EXECUTION_GRAPH_INDEX_COMPLEXITY,
)
from noetrium_platform.research.execution.policy.runtime.authority import (
    EXECUTION_PRIORITY_AGING_COMPLEXITY,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.contracts import (
    ASSIGNMENT_WORKLOAD_CACHED_LOOKUP_COMPLEXITY,
)


def test_proven_optimal_algorithms_publish_tight_time_contracts() -> None:
    contracts = (
        RESOURCE_CLAIM_ADMISSION_COMPLEXITY,
        RESOURCE_PHYSICAL_BINDING_LOOKUP_COMPLEXITY,
        RESOURCE_SNAPSHOT_FILTER_MATERIALIZATION_COMPLEXITY,
        RESOURCE_AFFECTED_RECONCILIATION_COMPLEXITY,
        MODEL_WARM_DOMINANCE_COMPLEXITY,
        MODEL_REPLICA_ROUTING_COMPLEXITY,
        RESEARCH_GRAPH_FRONTIER_COMPLEXITY,
        EXECUTION_GRAPH_INDEX_COMPLEXITY,
        SELECTED_EXECUTION_GRAPH_INDEX_COMPLEXITY,
        ASSIGNMENT_WORKLOAD_CACHED_LOOKUP_COMPLEXITY,
        EXECUTION_PRIORITY_AGING_COMPLEXITY,
        RESEARCH_EXECUTION_TOPOLOGY_COMPLEXITY,
        RESEARCH_EXECUTION_DESCENDANTS_COMPLEXITY,
        RESEARCH_EXECUTION_SEMANTIC_PROPAGATION_COMPLEXITY,
    )
    assert len({row.algorithm_id for row in contracts}) == len(contracts)
    assert len({row.contract_digest for row in contracts}) == len(contracts)
    assert all(row.time_tight for row in contracts)


def test_streaming_or_point_algorithms_publish_tight_space_when_proven() -> None:
    assert MODEL_REPLICA_ROUTING_COMPLEXITY.space_tight
    assert RESOURCE_PHYSICAL_BINDING_LOOKUP_COMPLEXITY.space_tight
    assert RESOURCE_SNAPSHOT_FILTER_MATERIALIZATION_COMPLEXITY.space_tight
    assert EXECUTION_GRAPH_INDEX_COMPLEXITY.space_tight
    assert SELECTED_EXECUTION_GRAPH_INDEX_COMPLEXITY.space_tight
    assert ASSIGNMENT_WORKLOAD_CACHED_LOOKUP_COMPLEXITY.space_tight
    assert EXECUTION_PRIORITY_AGING_COMPLEXITY.space_tight
    assert RESEARCH_EXECUTION_TOPOLOGY_COMPLEXITY.space_tight
    assert RESEARCH_EXECUTION_DESCENDANTS_COMPLEXITY.space_tight
    assert RESEARCH_EXECUTION_SEMANTIC_PROPAGATION_COMPLEXITY.space_tight


def test_physical_binding_lookup_contract_is_logarithmic() -> None:
    bound = RESOURCE_PHYSICAL_BINDING_LOOKUP_COMPLEXITY.time_upper_bound
    assert len(bound.terms) == 1
    factor = bound.terms[0].factors[0]
    assert factor.variable == "live_bindings"
    assert factor.power_numerator == 0
    assert factor.log_power == 1

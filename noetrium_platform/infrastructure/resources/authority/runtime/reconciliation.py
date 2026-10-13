from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.kernel import (
    canonical_digest,
    ComplexityBound,
    ComplexityContract,
)
from noetrium_platform.infrastructure.resources.api.topology_index import (
    ResourceTopologyIndex,
)

from ..api import (
    AuthoritySnapshot,
    ReconcileAction,
    ReconcileActionKind,
    ReconcilePlan,
    TicketState,
    binding_field,
    claim_field,
    is_resource_observation,
    observation_field,
    ticket_field,
)


RESOURCE_AFFECTED_RECONCILIATION_COMPLEXITY = ComplexityContract(
    algorithm_id="resource.reconciliation.affected-subgraph.v2",
    implementation_digest=canonical_digest(
        ("resource.reconciliation.affected-subgraph.v2", "multi-source-closure")
    ),
    time_upper_bound=ComplexityBound.linear_sum(
        "affected_resources",
        "affected_relations",
    ),
    space_upper_bound=ComplexityBound.linear_sum(
        "affected_resources",
        "affected_relations",
    ),
    assumptions=(
        "resource topology adjacency indexes are materialized",
        "every affected resource or relation can change the emitted reconcile action set",
    ),
    time_lower_bound=ComplexityBound.linear_sum(
        "affected_resources",
        "affected_relations",
    ),
)


class ResourceReconciliationPlanner:
    """Pure deterministic Desired/Authorized/Observed reconciliation planner.

    Desired structure comes only from NoetriumUnit. AuthoritySnapshot is the
    only dynamic truth. ResourceObservation is evidence and can never authorize
    a generation by itself.
    """

    def __init__(self, topology: NoetriumUnit) -> None:
        self._topology_index = ResourceTopologyIndex(topology)

    @property
    def topology_index(self) -> ResourceTopologyIndex:
        return self._topology_index

    def _observation(
        self,
        resource_id: str,
        observations: Mapping[str, NoetriumUnit],
    ) -> NoetriumUnit | None:
        observation = observations.get(resource_id)
        if observation is None:
            return None
        if not is_resource_observation(observation):
            raise TypeError("resource observation map must contain resource.observation Units")
        expected_key = self._topology_index.authority_key(resource_id)
        if observation_field(observation, "resource_key") != expected_key:
            raise ValueError(
                "resource observation authority key drifted: "
                f"resource={resource_id} expected={expected_key} "
                f"observed={observation_field(observation, "resource_key")}"
            )
        return observation

    @staticmethod
    def _observation_matches_ticket(
        ticket: NoetriumUnit,
        observation: NoetriumUnit | None,
    ) -> bool:
        return bool(
            observation is not None
            and observation_field(observation, "resource_key") == ticket_field(ticket, "resource_key")
            and observation_field(observation, "generation") == ticket_field(ticket, "generation")
            and observation_field(observation, "ticket_id") == ticket_field(ticket, "ticket_id")
            and observation_field(observation, "spec_digest") == ticket_field(ticket, "spec_digest")
        )

    def _claim_converged(
        self,
        resource_id: str,
        snapshot: AuthoritySnapshot,
    ) -> bool:
        key = self._topology_index.authority_key(resource_id)
        generation = snapshot.generation_for(key)
        if generation is None:
            return False
        claims = snapshot.current_claims_for(key)
        if len(claims) > 1:
            raise RuntimeError(
                f"authority snapshot contains multiple current claims for {key}"
            )
        return len(claims) == 1

    def _physical_converged(
        self,
        resource_id: str,
        snapshot: AuthoritySnapshot,
        observations: Mapping[str, NoetriumUnit],
    ) -> bool:
        if not self._topology_index.requires_realization(resource_id):
            return self._claim_converged(resource_id, snapshot)
        key = self._topology_index.authority_key(resource_id)
        generation = snapshot.generation_for(key)
        binding = snapshot.binding_for(key)
        observation = self._observation(resource_id, observations)
        return bool(
            generation is not None
            and self._claim_converged(resource_id, snapshot)
            and binding is not None
            and observation is not None
            and observation_field(observation, "exists")
            and observation_field(observation, "ready")
            and observation_field(observation, "generation") == generation.generation
            and observation_field(observation, "ticket_id") == binding_field(binding, "ticket_id")
            and observation_field(observation, "spec_digest") == binding_field(binding, "spec_digest")
        )

    def _recoverable_without_fence(
        self,
        resource_id: str,
        snapshot: AuthoritySnapshot,
        observations: Mapping[str, NoetriumUnit],
    ) -> bool:
        """Whether current generation can converge without being replaced."""
        if not self._claim_converged(resource_id, snapshot):
            return False
        if not self._topology_index.requires_realization(resource_id):
            return True
        key = self._topology_index.authority_key(resource_id)
        ticket = snapshot.current_ticket_for(key)
        observation = self._observation(resource_id, observations)
        if ticket is None:
            # Claim committed, provider effect not prepared yet.
            return True
        if ticket_field(ticket, "state") is TicketState.PREPARED:
            # Crash before effect, during a slow start, or after effect before
            # binding are all recoverable by replaying the same idempotent ticket.
            # Exact-ticket existence without READY is not generation drift.
            if observation is None:
                return True
            return self._observation_matches_ticket(ticket, observation)
        if ticket_field(ticket, "state") is TicketState.BOUND:
            # A bound realization must still be observed as the exact generation.
            return self._physical_converged(
                resource_id,
                snapshot,
                observations,
            )
        if ticket_field(ticket, "state") is TicketState.RETIRING:
            return False
        return False

    def plan(
        self,
        snapshot: AuthoritySnapshot,
        observations: Mapping[str, NoetriumUnit],
        *,
        desired_resource_ids: frozenset[str] | None = None,
    ) -> ReconcilePlan:
        if type(snapshot) is not AuthoritySnapshot:
            raise TypeError("reconciliation requires AuthoritySnapshot")
        known = self._topology_index.resource_ids
        desired = known if desired_resource_ids is None else desired_resource_ids
        if type(desired) is not frozenset:
            raise TypeError("desired resource ids must be frozenset")
        if not desired <= known:
            raise ValueError(
                "desired resource set contains nodes outside resource topology"
            )
        unknown_observations = frozenset(observations) - known
        if unknown_observations:
            raise ValueError(
                "observation set contains nodes outside resource topology: "
                f"{tuple(sorted(unknown_observations))}"
            )
        for resource_id in observations:
            self._observation(resource_id, observations)

        converged_desired = frozenset(
            resource_id
            for resource_id in desired
            if self._physical_converged(resource_id, snapshot, observations)
        )
        hard_rebuild_seeds: set[str] = set()
        for resource_id in desired - converged_desired:
            key = self._topology_index.authority_key(resource_id)
            generation = snapshot.generation_for(key)
            has_any_state = bool(
                generation is not None
                or snapshot.claims_for(key)
                or snapshot.tickets_for(key)
                or snapshot.binding_for(key) is not None
            )
            if has_any_state and not self._recoverable_without_fence(
                resource_id,
                snapshot,
                observations,
            ):
                hard_rebuild_seeds.add(resource_id)

        retire_set: set[str] = set(known - desired)
        if hard_rebuild_seeds:
            # Multi-source reverse closure visits each affected resource/edge at
            # most once. Computing one closure per seed can become O(S(V+E))
            # when many failed descendants overlap.
            retire_set.update(
                self._topology_index.reverse_dependency_closure(hard_rebuild_seeds)
            )

        # A durable generation row is a fencing epoch, not evidence that a
        # resource still exists. Retirement work remains only while ownership or
        # physical-effect state survives. Treating generation-only state as live
        # would advance the epoch forever after a successful desired=empty close.
        active_retire_set = {
            resource_id
            for resource_id in retire_set
            if (
                snapshot.claims_for(self._topology_index.authority_key(resource_id))
                or any(
                    ticket_field(ticket, "state") is not TicketState.RETIRED
                    for ticket in snapshot.tickets_for(
                        self._topology_index.authority_key(resource_id)
                    )
                )
                or snapshot.binding_for(self._topology_index.authority_key(resource_id))
                is not None
            )
        }
        release_order = self._topology_index.release_subset(active_retire_set)

        rows: list[tuple[ReconcileActionKind, str, str | None]] = []

        # Phase 1: advance generation first. This is the universal logical fence.
        fenced: set[str] = set()
        for resource_id in release_order:
            key = self._topology_index.authority_key(resource_id)
            if snapshot.generation_for(key) is not None:
                rows.append(
                    (
                        ReconcileActionKind.ADVANCE_GENERATION,
                        resource_id,
                        None,
                    )
                )
                fenced.add(resource_id)

        # Phase 2: retire physical effects in reverse dependency order. A
        # confirm-absent action is explicit because provider return is evidence,
        # not authority truth.
        for resource_id in release_order:
            if not self._topology_index.requires_realization(resource_id):
                continue
            key = self._topology_index.authority_key(resource_id)
            live_tickets = tuple(
                ticket
                for ticket in snapshot.tickets_for(key)
                if ticket_field(ticket, "state") is not TicketState.RETIRED
            )
            for ticket in sorted(
                live_tickets,
                key=lambda row: (ticket_field(row, "generation"), ticket_field(row, "ticket_id")),
                reverse=True,
            ):
                rows.append(
                    (
                        ReconcileActionKind.RETIRE,
                        resource_id,
                        ticket_field(ticket, "ticket_id"),
                    )
                )
                rows.append(
                    (
                        ReconcileActionKind.CONFIRM_ABSENT,
                        resource_id,
                        ticket_field(ticket, "ticket_id"),
                    )
                )

        # Phase 3: capacity/ownership claims are released only after upper
        # physical realizations have been driven absent.
        for resource_id in release_order:
            key = self._topology_index.authority_key(resource_id)
            for claim in sorted(
                snapshot.claims_for(key),
                key=lambda row: claim_field(row, "claim_id"),
            ):
                rows.append(
                    (
                        ReconcileActionKind.RELEASE_CLAIM,
                        resource_id,
                        claim_field(claim, "claim_id"),
                    )
                )

        # Phase 4: build desired closure in dependency order.
        for resource_id in self._topology_index.acquire_order:
            if resource_id not in desired:
                continue
            if (
                resource_id not in active_retire_set
                and resource_id in converged_desired
            ):
                continue

            key = self._topology_index.authority_key(resource_id)
            generation = snapshot.generation_for(key)
            current_claim = self._claim_converged(resource_id, snapshot)

            if generation is None:
                rows.append(
                    (
                        ReconcileActionKind.ADVANCE_GENERATION,
                        resource_id,
                        None,
                    )
                )
            elif resource_id in active_retire_set:
                # Phase 1 already advanced this generation.
                pass

            if resource_id in active_retire_set or not current_claim:
                rows.append(
                    (
                        ReconcileActionKind.ACQUIRE_CLAIM,
                        resource_id,
                        None,
                    )
                )

            if not self._topology_index.requires_realization(resource_id):
                continue

            if resource_id in active_retire_set:
                rows.extend(
                    (
                        (ReconcileActionKind.PREPARE, resource_id, None),
                        (ReconcileActionKind.REALIZE, resource_id, None),
                        (ReconcileActionKind.BIND, resource_id, None),
                    )
                )
                continue

            ticket = snapshot.current_ticket_for(key)
            observation = self._observation(resource_id, observations)
            if ticket is None:
                rows.extend(
                    (
                        (ReconcileActionKind.PREPARE, resource_id, None),
                        (ReconcileActionKind.REALIZE, resource_id, None),
                        (ReconcileActionKind.BIND, resource_id, None),
                    )
                )
                continue
            if ticket_field(ticket, "state") is TicketState.PREPARED:
                if (
                    observation is not None
                    and self._observation_matches_ticket(ticket, observation)
                    and observation_field(observation, "exists")
                    and observation_field(observation, "ready")
                ):
                    rows.append(
                        (
                            ReconcileActionKind.BIND,
                            resource_id,
                            ticket_field(ticket, "ticket_id"),
                        )
                    )
                else:
                    rows.extend(
                        (
                            (
                                ReconcileActionKind.REALIZE,
                                resource_id,
                                ticket_field(ticket, "ticket_id"),
                            ),
                            (
                                ReconcileActionKind.BIND,
                                resource_id,
                                ticket_field(ticket, "ticket_id"),
                            ),
                        )
                    )
                continue

            # Any other non-converged live ticket should have been classified as
            # a hard rebuild seed above. Reaching here would violate planner
            # completeness and must fail closed.
            raise RuntimeError(
                "non-converged physical generation escaped rebuild planning: "
                f"{resource_id}:{ticket_field(ticket, "state").value}"
            )

        actions = tuple(
            ReconcileAction(
                ordinal=index,
                kind=kind,
                resource_id=resource_id,
                reference_id=reference,
            )
            for index, (kind, resource_id, reference) in enumerate(rows)
        )
        return ReconcilePlan(
            topology_digest=self._topology_index.topology.semantic_digest,
            actions=actions,
        )


__all__ = ["ResourceReconciliationPlanner"]

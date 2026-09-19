"""Concrete validation for typed composition plans.

Only composition roots import this implementation. Projects receive the
``CapabilityCompositionPlannerPort`` declared by the architecture API.
"""

from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.governance.architecture.api.capability_composition import (
    AmbiguousCapabilityProvider,
    BindingDiagnostic,
    BindingDiagnosticCode,
    BindingDiagnosticReference,
    BindingDiagnosticReferenceKind,
    BindingDiagnosticSeverity,
    BindingEdge,
    BindingPlan,
    BindingRemediationCategory,
    CapabilityBindingError,
    CapabilityCompositionPlannerPort,
    CapabilityDependencyCycle,
    CapabilityInterfaceMismatch,
    CapabilityKey,
    CapabilityOffer,
    CapabilityRequirement,
    CompositionContract,
    CompositionContractError,
    CompositionIdentity,
    CompositionSubject,
    CompositionSubjectKind,
    CompositionTopologyError,
    MissingCapabilityProvider,
    ProviderSelection,
    RequirementAddress,
)
from noetrium_platform.foundation.governance.system_registry.api import SystemIdentity, SystemRegistryPort
from noetrium_platform.foundation.kernel.kernel import Sha256Digest, canonical_digest
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeRegistryPort


_ARCHITECTURE_SUBJECT = CompositionSubject.system_subject(
    SystemIdentity("governance", ("architecture",))
)


def _identity_refs(values: tuple[str, ...]) -> tuple[BindingDiagnosticReference, ...]:
    return tuple(
        BindingDiagnosticReference(BindingDiagnosticReferenceKind.IDENTITY, value)
        for value in sorted(values)
    )


def _binding_diagnostic(
    requirement: CapabilityRequirement,
    *,
    code: str,
    summary: str,
    remediation: BindingRemediationCategory,
    remediation_action: str,
    provider_identity: str | None = None,
    related_identities: tuple[str, ...] = (),
) -> BindingDiagnostic:
    return BindingDiagnostic(
        code=BindingDiagnosticCode(code),
        severity=BindingDiagnosticSeverity.ERROR,
        blocking=True,
        owner=_ARCHITECTURE_SUBJECT,
        subject=requirement.address.consumer,
        requirement_digest=Sha256Digest(canonical_digest(requirement)),
        summary=summary,
        requirement=requirement.address,
        provider_identity=provider_identity,
        related_refs=_identity_refs(related_identities),
        remediation=remediation,
        remediation_action=remediation_action,
    )


@dataclass(frozen=True, slots=True)
class _CapabilityOfferGroup:
    by_interface: dict[str, tuple[CapabilityOffer, ...]]
    offer_ids: tuple[str, ...]


def _freeze_offer_group(
    rows: dict[str, list[CapabilityOffer]],
    offer_ids: list[str],
) -> _CapabilityOfferGroup:
    by_interface: dict[str, tuple[CapabilityOffer, ...]] = {}
    for digest, offers in rows.items():
        by_interface[digest] = tuple(offers)
    return _CapabilityOfferGroup(by_interface, tuple(sorted(offer_ids)))


class CapabilityCompositionPlanner(CapabilityCompositionPlannerPort):
    """Validate and freeze a recursive capability graph at composition time."""

    def __init__(self, *, systems: SystemRegistryPort, scopes: ScopeRegistryPort) -> None:
        self._systems = systems
        self._scopes = scopes

    def freeze(
        self,
        identity: CompositionIdentity,
        contracts: tuple[CompositionContract, ...],
        *,
        imported_offers: tuple[CapabilityOffer, ...] = (),
        selections: tuple[ProviderSelection, ...] = (),
    ) -> BindingPlan:
        self._validate_identity(identity)
        self._validate_contracts(identity, contracts)
        self._validate_imported_offers(identity, imported_offers)
        normalized_contracts = self._normalize_contracts(contracts)
        offers = self._collect_offers(normalized_contracts, imported_offers)
        offer_index = self._index_offers(offers)
        requirements = self._collect_requirements(normalized_contracts)
        selected = self._selection_map(requirements, selections)
        edges: list[BindingEdge] = []
        for requirement in requirements:
            candidates = self._candidates(requirement, offer_index)
            choices = selected.get(requirement.address)
            resolved = self._resolve_requirement(requirement, candidates, choices)
            edges.extend(BindingEdge(requirement.address, offer) for offer in resolved)
        ordered_edges = tuple(
            sorted(
                edges,
                key=lambda edge: (
                    edge.requirement.consumer.key,
                    edge.requirement.requirement_id,
                    edge.offer.offer_id,
                ),
            )
        )
        self._reject_cycles(normalized_contracts, ordered_edges)
        ordered_imports = tuple(sorted(imported_offers, key=lambda offer: offer.offer_id))
        digest = canonical_digest(
            {
                "identity": identity,
                "contracts": normalized_contracts,
                "imports": ordered_imports,
                "edges": ordered_edges,
            }
        )
        return BindingPlan(identity, normalized_contracts, ordered_imports, ordered_edges, digest)

    def _validate_identity(self, identity: CompositionIdentity) -> None:
        if not self._scopes.contains(identity.scope):
            raise CompositionContractError(f"composition scope is not registered: {identity.scope.key}")
        if identity.owner.kind is CompositionSubjectKind.SYSTEM and (
            identity.owner.system is None or not self._systems.contains(identity.owner.system.key)
        ):
            raise CompositionTopologyError(
                f"composition owner is not registered: {identity.owner.subject_id}"
            )

    def _validate_contracts(
        self,
        identity: CompositionIdentity,
        contracts: tuple[CompositionContract, ...],
    ) -> None:
        subjects = [contract.subject for contract in contracts]
        if len(subjects) != len(set(subjects)):
            raise CompositionContractError("a composition plan contains a duplicate subject contract")
        if identity.owner.kind is CompositionSubjectKind.PROJECT:
            allowed = {identity.owner}
        else:
            assert identity.owner.system is not None
            allowed = {
                identity.owner,
                *(
                    CompositionSubject.system_subject(child.identity)
                    for child in self._systems.children(identity.owner.system.key)
                ),
            }
        for contract in contracts:
            if (
                contract.subject.kind is CompositionSubjectKind.SYSTEM
                and (
                    contract.subject.system is None
                    or not self._systems.contains(contract.subject.system.key)
                )
            ):
                raise CompositionTopologyError(
                    f"contract system is not registered: {contract.subject.subject_id}"
                )
            if contract.scope != identity.scope:
                raise CompositionContractError("a contract scope must equal its composition scope")
            if not self._scopes.contains(contract.scope):
                raise CompositionContractError(f"contract scope is not registered: {contract.scope.key}")
            if contract.subject not in allowed:
                owner = identity.owner.key
                raise CompositionTopologyError(
                    f"{owner} may compose only its local subject boundary, "
                    f"not {contract.subject.key}"
                )

    def _validate_imported_offers(
        self,
        identity: CompositionIdentity,
        imported_offers: tuple[CapabilityOffer, ...],
    ) -> None:
        """Imported boundaries must name a real external system authority.

        A local project can publish a project-owned offer inside its own
        contract, but it may not import a second project's binding and thereby
        create an undeclared project-to-project composition hierarchy.
        """

        for offer in imported_offers:
            if not self._scopes.contains(offer.scope):
                raise CompositionContractError(
                    f"imported offer scope is not registered: {offer.scope.key}"
                )
            if offer.owner.kind is CompositionSubjectKind.PROJECT:
                raise CompositionTopologyError(
                    f"{identity.owner.key} cannot import project-owned offer {offer.offer_id}; "
                    "project-local offers belong in the owning project contract"
                )
            if offer.owner.system is None or not self._systems.contains(offer.owner.system.key):
                raise CompositionTopologyError(
                    f"imported offer owner is not a registered system: {offer.owner.subject_id}"
                )

    @staticmethod
    def _normalize_contracts(
        contracts: tuple[CompositionContract, ...],
    ) -> tuple[CompositionContract, ...]:
        """Canonicalize declaration order before identity/digest materialization."""
        normalized = (
            CompositionContract(
                contract.subject,
                contract.scope,
                offers=tuple(sorted(contract.offers, key=lambda offer: offer.offer_id)),
                requirements=tuple(
                    sorted(contract.requirements, key=lambda requirement: requirement.address.value)
                ),
            )
            for contract in contracts
        )
        return tuple(sorted(normalized, key=lambda contract: contract.subject.key))

    @staticmethod
    def _collect_offers(
        contracts: tuple[CompositionContract, ...],
        imported_offers: tuple[CapabilityOffer, ...],
    ) -> tuple[CapabilityOffer, ...]:
        offers = tuple(offer for contract in contracts for offer in contract.offers) + imported_offers
        offer_ids = [offer.offer_id for offer in offers]
        if len(offer_ids) != len(set(offer_ids)):
            raise CompositionContractError("a composition plan contains a duplicate offer id")
        return tuple(sorted(offers, key=lambda offer: offer.offer_id))

    @staticmethod
    def _collect_requirements(
        contracts: tuple[CompositionContract, ...],
    ) -> tuple[CapabilityRequirement, ...]:
        requirements = tuple(
            requirement for contract in contracts for requirement in contract.requirements
        )
        addresses = [requirement.address for requirement in requirements]
        if len(addresses) != len(set(addresses)):
            raise CompositionContractError("a composition plan contains a duplicate requirement address")
        return tuple(sorted(requirements, key=lambda requirement: requirement.address.value))

    @staticmethod
    def _selection_map(
        requirements: tuple[CapabilityRequirement, ...],
        selections: tuple[ProviderSelection, ...],
    ) -> dict[RequirementAddress, tuple[str, ...]]:
        known = {requirement.address for requirement in requirements}
        result: dict[RequirementAddress, tuple[str, ...]] = {}
        for selection in selections:
            if selection.requirement not in known:
                raise CompositionContractError(
                    f"selection names an unknown requirement: {selection.requirement.value}"
                )
            if selection.requirement in result:
                raise CompositionContractError(
                    f"requirement has more than one provider selection: {selection.requirement.value}"
                )
            result[selection.requirement] = tuple(sorted(selection.offer_ids))
        return result

    @staticmethod
    def _index_offers(
        offers: tuple[CapabilityOffer, ...],
    ) -> dict[CapabilityKey, _CapabilityOfferGroup]:
        """Index providers once so requirement lookup avoids whole-plan rescans."""
        staged: dict[CapabilityKey, dict[str, list[CapabilityOffer]]] = {}
        offer_ids: dict[CapabilityKey, list[str]] = {}
        for offer in offers:
            by_interface = staged.setdefault(offer.capability, {})
            by_interface.setdefault(offer.interface_digest, []).append(offer)
            offer_ids.setdefault(offer.capability, []).append(offer.offer_id)
        return {
            capability: _freeze_offer_group(by_interface, offer_ids[capability])
            for capability, by_interface in staged.items()
        }

    def _candidates(
        self,
        requirement: CapabilityRequirement,
        offer_index: dict[CapabilityKey, _CapabilityOfferGroup],
    ) -> tuple[CapabilityOffer, ...]:
        group = offer_index.get(requirement.capability)
        if group is None:
            return ()
        same_interface = group.by_interface.get(requirement.interface_digest)
        if same_interface is None:
            raise CapabilityInterfaceMismatch(_binding_diagnostic(
                requirement,
                code="governance.binding.interface-mismatch",
                summary=(
                    f"interface digest mismatch for {requirement.address.value}; "
                    f"offers={', '.join(group.offer_ids)}"
                ),
                remediation=BindingRemediationCategory.INTERFACE,
                remediation_action="provider.interface.align",
                related_identities=group.offer_ids,
            ))
        return tuple(
            offer for offer in same_interface if self._visible_at_scope(offer, requirement.scope)
        )

    def _visible_at_scope(self, offer: CapabilityOffer, consumer_scope: ScopeIdentity) -> bool:
        if offer.scope == consumer_scope:
            return True
        if not offer.exported_to_descendants:
            return False
        return offer.scope in self._scopes.ancestry(consumer_scope)

    @staticmethod
    def _resolve_requirement(
        requirement: CapabilityRequirement,
        candidates: tuple[CapabilityOffer, ...],
        selected_ids: tuple[str, ...] | None,
    ) -> tuple[CapabilityOffer, ...]:
        candidates_by_id = {offer.offer_id: offer for offer in candidates}
        if selected_ids is not None:
            missing = tuple(offer_id for offer_id in selected_ids if offer_id not in candidates_by_id)
            if missing:
                raise CapabilityBindingError(_binding_diagnostic(
                    requirement,
                    code="governance.binding.selection-ineligible",
                    summary=(
                        f"selection for {requirement.address.value} names ineligible offers: "
                        f"{', '.join(missing)}"
                    ),
                    remediation=BindingRemediationCategory.PROVIDER_SELECTION,
                    remediation_action="provider.selection.revise",
                    related_identities=missing,
                ))
            resolved = tuple(candidates_by_id[offer_id] for offer_id in selected_ids)
        elif len(candidates) == 1:
            resolved = candidates
        elif not candidates and requirement.optional:
            return ()
        elif not candidates:
            raise MissingCapabilityProvider(_binding_diagnostic(
                requirement,
                code="governance.binding.provider-missing",
                summary=(
                    f"no provider for {requirement.address.value} "
                    f"({requirement.capability.value})"
                ),
                remediation=BindingRemediationCategory.CAPABILITY,
                remediation_action="provider.capability.configure",
            ))
        else:
            options = ", ".join(offer.offer_id for offer in candidates)
            raise AmbiguousCapabilityProvider(_binding_diagnostic(
                requirement,
                code="governance.binding.provider-ambiguous",
                summary=(
                    f"multiple providers for {requirement.address.value}: "
                    f"{options}; select explicitly"
                ),
                remediation=BindingRemediationCategory.PROVIDER_SELECTION,
                remediation_action="provider.selection.choose",
                related_identities=tuple(offer.offer_id for offer in candidates),
            ))
        if requirement.cardinality.value == "exactly_one" and len(resolved) != 1:
            raise CapabilityBindingError(_binding_diagnostic(
                requirement,
                code="governance.binding.cardinality-mismatch",
                summary=(
                    f"{requirement.address.value} requires exactly one provider, "
                    f"got {len(resolved)}"
                ),
                remediation=BindingRemediationCategory.PROVIDER_SELECTION,
                remediation_action="provider.selection.revise",
                related_identities=tuple(offer.offer_id for offer in resolved),
            ))
        if requirement.cardinality.value == "one_or_more" and not resolved:
            if requirement.optional:
                return ()
            raise MissingCapabilityProvider(_binding_diagnostic(
                requirement,
                code="governance.binding.provider-missing",
                summary=(
                    f"no provider for {requirement.address.value} "
                    f"({requirement.capability.value})"
                ),
                remediation=BindingRemediationCategory.CAPABILITY,
                remediation_action="provider.capability.configure",
            ))
        return resolved

    @staticmethod
    def _reject_cycles(
        contracts: tuple[CompositionContract, ...],
        edges: tuple[BindingEdge, ...],
    ) -> None:
        local = {contract.subject.key for contract in contracts}
        graph: dict[str, set[str]] = {subject: set() for subject in local}
        for edge in edges:
            consumer = edge.requirement.consumer.key
            provider = edge.offer.owner.key
            if consumer in local and provider in local and consumer != provider:
                graph[consumer].add(provider)
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str, trail: tuple[str, ...]) -> None:
            if node in visiting:
                cycle = " -> ".join((*trail, node))
                raise CapabilityDependencyCycle(f"capability dependency cycle: {cycle}")
            if node in visited:
                return
            visiting.add(node)
            for target in sorted(graph[node]):
                visit(target, (*trail, node))
            visiting.remove(node)
            visited.add(node)

        for node in sorted(graph):
            visit(node, ())


__all__ = ["CapabilityCompositionPlanner"]

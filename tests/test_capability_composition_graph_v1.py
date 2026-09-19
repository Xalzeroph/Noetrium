from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from noetrium_platform.foundation.governance.system_registry.api import SystemIdentity
from noetrium_platform.foundation.governance.system_registry.runtime import build_default_system_registry
from noetrium_platform.foundation.governance.architecture.api.capability_composition import (
    AmbiguousCapabilityProvider,
    BindingDiagnostic,
    BindingDiagnosticCode,
    BindingDiagnosticReference,
    BindingDiagnosticReferenceKind,
    BindingDiagnosticSeverity,
    BindingProof,
    BindingRemediationCategory,
    BindingResolution,
    BindingResolutionState,
    BindingResolverPort,
    CapabilityDependencyCycle,
    CapabilityInterfaceMismatch,
    CapabilityKey,
    CapabilityOffer,
    CapabilityRequirement,
    CompositionContract,
    CompositionContractError,
    CompositionIdentity,
    CompositionSubject,
    CompositionTopologyError,
    MissingCapabilityProvider,
    ProviderSelection,
    RequirementAddress,
    interface_contract_digest,
)
from noetrium_platform.foundation.governance.architecture.runtime.capability_composition import (
    CapabilityCompositionPlanner,
)
from noetrium_platform.foundation.kernel.kernel import Sha256Digest, canonical_digest
from noetrium_platform.infrastructure.lifecycle.host.api import OperatingSystemRoute
from noetrium_platform.infrastructure.lifecycle.server.identity.api import ServerConnectionFactoryPort
from noetrium_platform.evidence.observability.logging.record.api import LoggingSystemPort
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, ScopeIdentity, ScopeKind
from noetrium_platform.foundation.scope.runtime import InMemoryScopeRegistry


HOST_ROUTE = CapabilityKey("runtime.host", "operating-system-route", 1)
SERVER_FACTORY = CapabilityKey("runtime.server", "connection-factory", 1)


def _scope_registry() -> InMemoryScopeRegistry:
    scopes = InMemoryScopeRegistry()
    workspace = ScopeIdentity(ScopeKind.WORKSPACE, "workspace")
    program = ScopeIdentity(ScopeKind.PROGRAM, "program")
    project = ScopeIdentity(ScopeKind.PROJECT, "project")
    scopes.register(workspace, PLATFORM_SCOPE)
    scopes.register(program, workspace)
    scopes.register(project, program)
    return scopes


def _offer(
    *,
    offer_id: str,
    owner: CompositionSubject,
    capability: CapabilityKey,
    interface: type,
    scope: ScopeIdentity = PLATFORM_SCOPE,
    exported: bool = True,
) -> CapabilityOffer:
    return CapabilityOffer(
        offer_id=offer_id,
        owner=owner,
        scope=scope,
        capability=capability,
        interface_digest=interface_contract_digest(interface),
        provider_identity=f"{offer_id}.provider",
        configuration_digest=canonical_digest({"offer_id": offer_id, "scope": scope.key}),
        exported_to_descendants=exported,
    )


def _requirement(
    *,
    consumer: CompositionSubject,
    requirement_id: str,
    capability: CapabilityKey,
    interface: type,
    scope: ScopeIdentity = PLATFORM_SCOPE,
) -> CapabilityRequirement:
    return CapabilityRequirement(
        address=RequirementAddress(consumer, requirement_id),
        scope=scope,
        capability=capability,
        interface_digest=interface_contract_digest(interface),
    )


def _system(system_id: str, path: tuple[str, ...] = ()) -> CompositionSubject:
    return CompositionSubject.system_subject(SystemIdentity(system_id, path))


def test_plan_is_stable_metadata_and_never_a_runtime_container() -> None:
    systems = build_default_system_registry()
    scopes = _scope_registry()
    host = _system("runtime", ("host",))
    server = _system("runtime", ("server",))
    offer = _offer(
        offer_id="local.host-route",
        owner=host,
        capability=HOST_ROUTE,
        interface=OperatingSystemRoute,
    )
    requirement = _requirement(
        consumer=server,
        requirement_id="host-route",
        capability=HOST_ROUTE,
        interface=OperatingSystemRoute,
    )
    planner = CapabilityCompositionPlanner(systems=systems, scopes=scopes)
    plan = planner.freeze(
        CompositionIdentity("runtime.infrastructure", PLATFORM_SCOPE, _system("runtime")),
        (
            CompositionContract(host, PLATFORM_SCOPE, offers=(offer,)),
            CompositionContract(server, PLATFORM_SCOPE, requirements=(requirement,)),
        ),
    )

    assert plan.bindings_for(requirement.address)[0].offer == offer
    assert len(plan.digest) == 64
    assert not hasattr(plan, "resolve")
    assert not hasattr(plan, "get")


def test_ambiguous_provider_requires_explicit_selection() -> None:
    systems = build_default_system_registry()
    scopes = _scope_registry()
    host = _system("runtime", ("host",))
    server = _system("runtime", ("server",))
    requirement = _requirement(
        consumer=server,
        requirement_id="host-route",
        capability=HOST_ROUTE,
        interface=OperatingSystemRoute,
    )
    contracts = (
        CompositionContract(
            host,
            PLATFORM_SCOPE,
            offers=(
                _offer(offer_id="host.a", owner=host, capability=HOST_ROUTE, interface=OperatingSystemRoute),
                _offer(offer_id="host.b", owner=host, capability=HOST_ROUTE, interface=OperatingSystemRoute),
            ),
        ),
        CompositionContract(server, PLATFORM_SCOPE, requirements=(requirement,)),
    )
    planner = CapabilityCompositionPlanner(systems=systems, scopes=scopes)
    identity = CompositionIdentity("runtime.infrastructure", PLATFORM_SCOPE, _system("runtime"))

    with pytest.raises(AmbiguousCapabilityProvider) as raised:
        planner.freeze(identity, contracts)
    diagnostic = raised.value.diagnostic
    assert diagnostic.code.value == "governance.binding.provider-ambiguous"
    assert diagnostic.requirement == requirement.address
    assert diagnostic.requirement_digest == Sha256Digest(canonical_digest(requirement))
    assert tuple(ref.reference_id for ref in diagnostic.related_refs) == ("host.a", "host.b")

    plan = planner.freeze(
        identity,
        contracts,
        selections=(ProviderSelection(requirement.address, ("host.b",)),),
    )
    assert plan.bindings_for(requirement.address)[0].offer.offer_id == "host.b"


def test_incompatible_interface_digest_fails_before_binding() -> None:
    systems = build_default_system_registry()
    scopes = _scope_registry()
    host = _system("runtime", ("host",))
    server = _system("runtime", ("server",))
    offer = _offer(
        offer_id="local.host-route",
        owner=host,
        capability=HOST_ROUTE,
        interface=OperatingSystemRoute,
    )
    requirement = _requirement(
        consumer=server,
        requirement_id="host-route",
        capability=HOST_ROUTE,
        interface=ServerConnectionFactoryPort,
    )
    planner = CapabilityCompositionPlanner(systems=systems, scopes=scopes)

    with pytest.raises(CapabilityInterfaceMismatch) as raised:
        planner.freeze(
            CompositionIdentity("runtime.infrastructure", PLATFORM_SCOPE, _system("runtime")),
            (
                CompositionContract(host, PLATFORM_SCOPE, offers=(offer,)),
                CompositionContract(server, PLATFORM_SCOPE, requirements=(requirement,)),
            ),
        )
    diagnostic = raised.value.diagnostic
    assert diagnostic.code.value == "governance.binding.interface-mismatch"
    assert diagnostic.remediation is BindingRemediationCategory.INTERFACE
    assert tuple(ref.reference_id for ref in diagnostic.related_refs) == ("local.host-route",)


def test_missing_provider_failure_carries_typed_machine_diagnostic() -> None:
    systems = build_default_system_registry()
    scopes = _scope_registry()
    server = _system("runtime", ("server",))
    requirement = _requirement(
        consumer=server, requirement_id="host-route",
        capability=HOST_ROUTE, interface=OperatingSystemRoute,
    )
    planner = CapabilityCompositionPlanner(systems=systems, scopes=scopes)
    with pytest.raises(MissingCapabilityProvider) as raised:
        planner.freeze(
            CompositionIdentity("runtime.infrastructure", PLATFORM_SCOPE, _system("runtime")),
            (CompositionContract(server, PLATFORM_SCOPE, requirements=(requirement,)),),
        )
    diagnostic = raised.value.diagnostic
    assert diagnostic.code.value == "governance.binding.provider-missing"
    assert diagnostic.blocking
    assert diagnostic.owner == _system("governance", ("architecture",))
    assert diagnostic.subject == server
    assert diagnostic.provider_identity is None
    assert diagnostic.remediation is BindingRemediationCategory.CAPABILITY


def test_plan_rejects_cycles_and_nonlocal_child_composition() -> None:
    systems = build_default_system_registry()
    scopes = _scope_registry()
    host = _system("runtime", ("host",))
    server = _system("runtime", ("server",))
    host_offer = _offer(
        offer_id="host.route",
        owner=host,
        capability=HOST_ROUTE,
        interface=OperatingSystemRoute,
    )
    server_offer = _offer(
        offer_id="server.factory",
        owner=server,
        capability=SERVER_FACTORY,
        interface=ServerConnectionFactoryPort,
    )
    planner = CapabilityCompositionPlanner(systems=systems, scopes=scopes)
    identity = CompositionIdentity("runtime.infrastructure", PLATFORM_SCOPE, _system("runtime"))
    with pytest.raises(CapabilityDependencyCycle):
        planner.freeze(
            identity,
            (
                CompositionContract(
                    host,
                    PLATFORM_SCOPE,
                    offers=(host_offer,),
                    requirements=(
                        _requirement(
                            consumer=host,
                            requirement_id="server-factory",
                            capability=SERVER_FACTORY,
                            interface=ServerConnectionFactoryPort,
                        ),
                    ),
                ),
                CompositionContract(
                    server,
                    PLATFORM_SCOPE,
                    offers=(server_offer,),
                    requirements=(
                        _requirement(
                            consumer=server,
                            requirement_id="host-route",
                            capability=HOST_ROUTE,
                            interface=OperatingSystemRoute,
                        ),
                    ),
                ),
            ),
        )


def test_project_subject_binds_imported_system_offer_without_becoming_a_system_node() -> None:
    systems = build_default_system_registry()
    scopes = _scope_registry()
    project_scope = ScopeIdentity(ScopeKind.PROJECT, "project")
    logging = _system("observability", ("logging",))
    project = CompositionSubject.project_subject("example-project", "1")
    logging_capability = CapabilityKey("observability.logging", "system", 1)
    logging_offer = _offer(
        offer_id="logging.platform-system",
        owner=logging,
        capability=logging_capability,
        interface=LoggingSystemPort,
    )
    requirement = _requirement(
        consumer=project,
        requirement_id="platform-logging",
        capability=logging_capability,
        interface=LoggingSystemPort,
        scope=project_scope,
    )
    planner = CapabilityCompositionPlanner(systems=systems, scopes=scopes)
    plan = planner.freeze(
        CompositionIdentity("project.example-project", project_scope, project),
        (CompositionContract(project, project_scope, requirements=(requirement,)),),
        imported_offers=(logging_offer,),
    )

    assert plan.bindings_for(requirement.address)[0].offer == logging_offer
    assert plan.contracts[0].subject == project
    assert plan.contracts[0].subject.kind.value == "project"
    assert not systems.contains("example-project")

    with pytest.raises(CompositionTopologyError):
        planner.freeze(
            CompositionIdentity("project.example-project", project_scope, project),
            (
                CompositionContract(project, project_scope),
                CompositionContract(_system("runtime", ("host",)), project_scope),
            ),
        )

    with pytest.raises(CompositionTopologyError):
        planner.freeze(
            CompositionIdentity("runtime.infrastructure", PLATFORM_SCOPE, _system("runtime")),
            (
                CompositionContract(
                    _system("runtime", ("server", "identity")),
                    PLATFORM_SCOPE,
                ),
            ),
        )


def test_imported_offer_must_belong_to_a_registered_system() -> None:
    systems = build_default_system_registry()
    scopes = _scope_registry()
    project_scope = ScopeIdentity(ScopeKind.PROJECT, "project")
    project = CompositionSubject.project_subject("example-project", "1")
    unregistered = _system("unregistered", ("logging",))
    imported = _offer(
        offer_id="unregistered.logging",
        owner=unregistered,
        capability=CapabilityKey("observability.logging", "system", 1),
        interface=LoggingSystemPort,
    )
    planner = CapabilityCompositionPlanner(systems=systems, scopes=scopes)

    with pytest.raises(CompositionTopologyError, match="not a registered system"):
        planner.freeze(
            CompositionIdentity("project.example-project", project_scope, project),
            (CompositionContract(project, project_scope),),
            imported_offers=(imported,),
        )


def test_large_plan_is_order_invariant_and_binds_by_capability() -> None:
    systems = build_default_system_registry()
    scopes = _scope_registry()
    host = _system("runtime", ("host",))
    server = _system("runtime", ("server",))
    rows = []
    for index in range(128):
        capability = CapabilityKey("runtime.scale", f"cap-{index:03d}", 1)
        rows.append((
            _offer(
                offer_id=f"offer-{index:03d}",
                owner=host,
                capability=capability,
                interface=OperatingSystemRoute,
            ),
            _requirement(
                consumer=server,
                requirement_id=f"cap-{index:03d}",
                capability=capability,
                interface=OperatingSystemRoute,
            ),
        ))
    planner = CapabilityCompositionPlanner(systems=systems, scopes=scopes)
    identity = CompositionIdentity("runtime.scale-plan", PLATFORM_SCOPE, _system("runtime"))
    def freeze(items):
        return planner.freeze(
            identity,
            (
                CompositionContract(
                    host,
                    PLATFORM_SCOPE,
                    offers=tuple(item[0] for item in items),
                ),
                CompositionContract(
                    server,
                    PLATFORM_SCOPE,
                    requirements=tuple(item[1] for item in items),
                ),
            ),
        )

    forward = freeze(tuple(rows))
    reverse = freeze(tuple(reversed(rows)))
    assert forward.digest == reverse.digest
    assert forward.edges == reverse.edges
    assert len(forward.edges) == 128
    assert tuple(edge.offer.offer_id for edge in forward.edges) == tuple(
        f"offer-{index:03d}" for index in range(128)
    )


def test_interface_digest_tracks_inherited_port_surface() -> None:
    def accepts_int(self, value: int) -> str: ...
    def accepts_str(self, value: str) -> str: ...

    int_base = type("BasePort", (), {"operation": accepts_int})
    str_base = type("BasePort", (), {"operation": accepts_str})
    int_port = type("DerivedPort", (int_base,), {})
    str_port = type("DerivedPort", (str_base,), {})
    for port in (int_port, str_port):
        port.__module__ = "contract_probe"
        port.__qualname__ = "DerivedPort"

    assert interface_contract_digest(int_port) != interface_contract_digest(str_port)


def _blocking_binding_diagnostic(
    *, subject: CompositionSubject, owner: CompositionSubject
) -> BindingDiagnostic:
    requirement = RequirementAddress(subject, "model-provider")
    return BindingDiagnostic(
        code=BindingDiagnosticCode("model.binding.capability-missing"),
        severity=BindingDiagnosticSeverity.ERROR,
        blocking=True,
        owner=owner,
        subject=subject,
        requirement_digest=Sha256Digest("a" * 64),
        summary="No compatible model provider is currently bindable.",
        requirement=requirement,
        provider_identity="model.local",
        provider_profile_digest=Sha256Digest("b" * 64),
        related_refs=(
            BindingDiagnosticReference(
                BindingDiagnosticReferenceKind.EVIDENCE, "evidence:model-canary-17"
            ),
        ),
        remediation=BindingRemediationCategory.QUALIFICATION,
        remediation_action="model.qualification.refresh",
    )


def test_binding_diagnostic_envelope_has_stable_machine_identity_not_prose_identity() -> None:
    subject = CompositionSubject.project_subject("paper", "1")
    owner = _system("model")
    diagnostic = _blocking_binding_diagnostic(subject=subject, owner=owner)
    reworded = replace(diagnostic, summary="Human wording may change without changing diagnosis truth.")

    assert diagnostic.machine_digest == reworded.machine_digest
    assert diagnostic.code.value == "model.binding.capability-missing"
    assert diagnostic.requirement is not None and diagnostic.requirement.consumer == subject
    assert diagnostic.related_refs[0].kind is BindingDiagnosticReferenceKind.EVIDENCE
    with pytest.raises(CompositionContractError, match="namespaced token"):
        BindingDiagnosticCode("MODEL_CAPABILITY_MISSING")


def test_binding_resolution_preserves_distinct_domain_payload_types() -> None:
    @dataclass(frozen=True, slots=True)
    class ModelDomainBinding:
        model_id: str

    @dataclass(frozen=True, slots=True)
    class ParticipantDomainBinding:
        participant_id: str

    subject = CompositionSubject.project_subject("paper", "1")
    evidence = (BindingDiagnosticReference(
        BindingDiagnosticReferenceKind.EVIDENCE, "evidence:binding-proof"
    ),)
    model_binding = ModelDomainBinding("model-a")
    model_proof = BindingProof(
        owner=_system("model"), subject=subject, requirement_digest=Sha256Digest("c" * 64),
        provider_identity="model.local", provider_profile_digest=Sha256Digest("d" * 64),
        binding_generation="generation-1", evidence_refs=evidence,
    )
    participant_binding = ParticipantDomainBinding("participant-a")
    participant_proof = BindingProof(
        owner=_system("participant"), subject=subject, requirement_digest=Sha256Digest("e" * 64),
        provider_identity="participant.local", provider_profile_digest=Sha256Digest("f" * 64),
        binding_generation="generation-9", evidence_refs=evidence,
    )

    model = BindingResolution.bound(model_binding, model_proof)
    participant = BindingResolution.bound(participant_binding, participant_proof)
    assert model.binding is model_binding and type(model.binding) is ModelDomainBinding
    assert participant.binding is participant_binding and type(participant.binding) is ParticipantDomainBinding
    assert model.proof is model_proof and participant.proof is participant_proof
    assert model.diagnostics == () and participant.diagnostics == ()


def test_binding_resolution_is_fail_closed_and_cannot_mix_success_with_diagnostics() -> None:
    subject = CompositionSubject.project_subject("paper", "1")
    diagnostic = _blocking_binding_diagnostic(subject=subject, owner=_system("model"))
    diagnosed = BindingResolution.diagnosed((diagnostic,))
    assert diagnosed.binding is None and diagnosed.proof is None
    assert diagnosed.diagnostics == (diagnostic,)

    nonblocking = replace(diagnostic, blocking=False, severity=BindingDiagnosticSeverity.WARNING)
    with pytest.raises(CompositionContractError, match="at least one blocking"):
        BindingResolution.diagnosed((nonblocking,))

    proof = BindingProof(
        owner=_system("model"), subject=subject, requirement_digest=Sha256Digest("1" * 64),
        provider_identity="model.local", provider_profile_digest=Sha256Digest("2" * 64),
        binding_generation="generation-2",
    )
    with pytest.raises(CompositionContractError, match="no diagnostics"):
        BindingResolution(binding=object(), proof=proof, diagnostics=(diagnostic,))
    with pytest.raises(CompositionContractError, match="requires proof"):
        BindingResolution(binding=object())


def test_binding_envelope_rejects_untyped_or_cross_subject_metadata() -> None:
    project = CompositionSubject.project_subject("paper", "1")
    other = CompositionSubject.project_subject("other", "1")
    diagnostic = _blocking_binding_diagnostic(subject=project, owner=_system("model"))
    with pytest.raises(CompositionContractError, match="consumer must equal diagnostic subject"):
        replace(diagnostic, subject=other)
    with pytest.raises(CompositionContractError, match="provider_profile_digest must be typed"):
        replace(diagnostic, provider_profile_digest="b" * 64)
    with pytest.raises(CompositionContractError, match="remediation_action must be a namespaced token"):
        replace(diagnostic, remediation_action="refresh")


def test_binding_diagnostic_examples_are_complete_ordered_and_digest_stable() -> None:
    subject = CompositionSubject.project_subject("paper", "1")
    owner = _system("model")
    base = _blocking_binding_diagnostic(subject=subject, owner=owner)
    rows = (
        replace(
            base, code=BindingDiagnosticCode("governance.binding.provider-missing"),
            provider_identity=None, provider_profile_digest=None,
            remediation=BindingRemediationCategory.CAPABILITY,
            remediation_action="provider.capability.configure",
        ),
        replace(
            base, code=BindingDiagnosticCode("governance.binding.provider-ambiguous"),
            remediation=BindingRemediationCategory.PROVIDER_SELECTION,
            remediation_action="provider.selection.choose",
        ),
        replace(
            base, code=BindingDiagnosticCode("governance.binding.capability-mismatch"),
            remediation=BindingRemediationCategory.INTERFACE,
            remediation_action="provider.interface.align",
        ),
        replace(
            base, code=BindingDiagnosticCode("model.binding.qualification-unready"),
            remediation=BindingRemediationCategory.QUALIFICATION,
            remediation_action="model.qualification.refresh",
        ),
        replace(
            base, code=BindingDiagnosticCode("participant.binding.provenance-drift"),
            owner=_system("participant"),
            remediation=BindingRemediationCategory.OWNER_ACTION,
            remediation_action="participant.provenance.rebind",
        ),
    )

    forward = BindingResolution.diagnosed(rows)
    reverse = BindingResolution.diagnosed(tuple(reversed(rows)))
    expected_codes = tuple(sorted(row.code.value for row in rows))
    assert forward.state is BindingResolutionState.DIAGNOSTIC
    assert tuple(row.code.value for row in forward.diagnostics) == expected_codes
    assert reverse.diagnostics == forward.diagnostics
    assert reverse.projection_digest == forward.projection_digest
    assert {row.remediation for row in forward.diagnostics} == {
        BindingRemediationCategory.CAPABILITY,
        BindingRemediationCategory.PROVIDER_SELECTION,
        BindingRemediationCategory.INTERFACE,
        BindingRemediationCategory.QUALIFICATION,
        BindingRemediationCategory.OWNER_ACTION,
    }


def test_success_projection_digest_is_neutral_and_domain_payload_identity_stays_owned() -> None:
    @dataclass(frozen=True, slots=True)
    class DomainBinding:
        domain_revision: str

    subject = CompositionSubject.project_subject("paper", "1")
    proof = BindingProof(
        owner=_system("model"), subject=subject, requirement_digest=Sha256Digest("3" * 64),
        provider_identity="model.local", provider_profile_digest=Sha256Digest("4" * 64),
        binding_generation="generation-3",
    )
    first = BindingResolution.bound(DomainBinding("domain-a"), proof)
    second = BindingResolution.bound(DomainBinding("domain-b"), proof)
    assert first.state is BindingResolutionState.BOUND
    assert first.projection_digest == second.projection_digest
    assert first.binding != second.binding
    assert first.proof.digest == proof.digest


def test_binding_resolution_rejects_duplicate_machine_diagnostics_and_mutable_sequence() -> None:
    subject = CompositionSubject.project_subject("paper", "1")
    diagnostic = _blocking_binding_diagnostic(subject=subject, owner=_system("model"))
    reworded = replace(diagnostic, summary="Different prose, same machine diagnosis.")
    with pytest.raises(CompositionContractError, match="machine-unique"):
        BindingResolution.diagnosed((diagnostic, reworded))
    with pytest.raises(CompositionContractError, match="immutable tuple"):
        BindingResolution(diagnostics=[diagnostic])  # type: ignore[arg-type]


def test_binding_envelope_is_exported_from_public_architecture_api() -> None:
    from noetrium_platform.foundation.governance.architecture import api as architecture_api

    assert architecture_api.BindingDiagnostic is BindingDiagnostic
    assert architecture_api.BindingProof is BindingProof
    assert architecture_api.BindingResolution is BindingResolution
    assert architecture_api.BindingResolverPort is BindingResolverPort

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import RLock

from noetrium_platform.capabilities.model.api import (
    ModelCapabilityRequirement,
    ModelProviderProfile,
    ProjectModelBinding,
)
from noetrium_platform.capabilities.model.composition.binding_resolution import (
    project_bound_model_resolution,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointReplicaSet,
)
from noetrium_platform.capabilities.model.serving.endpoint.providers import (
    ExactModelTokenizationCache,
    PersistedQualifiedModelEndpointBinding,
    QualifiedEndpointTokenizationProvider,
    QualifiedModelClosureReadError,
    load_qualified_model_deployment_closure,
)
from noetrium_platform.capabilities.model.serving.providers import (
    DirectoryRuntimeCanaryEvidenceStore,
    DirectoryRuntimeQualificationEvidenceStore,
)
from noetrium_platform.foundation.governance.architecture.api import (
    BindingDiagnostic,
    BindingDiagnosticCode,
    BindingDiagnosticSeverity,
    BindingProof,
    BindingRemediationCategory,
    BindingResolution,
    CompositionSubject,
)
from noetrium_platform.foundation.governance.system_registry.api import SystemIdentity
from noetrium_platform.foundation.kernel.kernel import (
    DirectoryMachineJournal,
    Sha256Digest,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.evidence.data.dataset.api import DatasetIdentity
from noetrium_platform.infrastructure.reliability.effect.api import EffectIntentJournal
from noetrium_platform.infrastructure.resources.directory.api import ManagedDirectoryKind
from noetrium_platform.foundation.portfolio.api import (
    ProjectCapabilityRequirement,
    ProjectManifest,
)
from noetrium_platform.product.research_os import (
    ResearchDefinitionKind,
    ResearchPortfolio,
)
from noetrium_platform.research.experimentation.api import (
    ResearchModelRoleRequirement,
    ResearchParticipantRequirement,
    materialize_research_study_spec,
    resolve_research_requirements,
)
from noetrium_platform.research.experimentation.lifecycle.api import (
    TrialTaskProjectionPort,
)
from noetrium_platform.research.experimentation.lifecycle.study.providers import (
    StandardWorkloadMeasurementProjection,
    WorkloadTrialProvider,
)
from noetrium_platform.research.experimentation.workload.api import (
    TaskDefinitionExperimentTaskProjection,
)
from noetrium_platform.research.experimentation.workload.composition import (
    bind_workload_graph,
    compose_method_runtime_bindings,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodRuntimePortInventory,
)
from noetrium_platform.research.execution.workflow.composition import (
    MethodAgentLoopRouter,
    MethodAgentPanelLoop,
    MethodModelAgentLoop,
    MethodModelEndpointBinding,
    MethodViewChatRequestFactory,
)
from .research_binding_authority import (
    ResearchBindingAuthority,
    ResearchBindingResolutionContext,
    ResearchCapabilityBindingRegistry,
    ResearchBindingRequirementMissing,
)
from .research_definition_authority import (
    ResearchDefinitionBinding,
    ResearchDefinitionBindingRegistry,
)
from .research_execution_manifest import PortfolioDerivedProjectManifestResolver
from .model_runtime_bootstrap import RequiredModelRuntime
from .model_runtime_refresh import refresh_required_qualified_model_runtimes
from .research_model_requirements import research_model_requirement_semantics
from .research_execution_content import (
    ResearchExecutionTrialReceiptPublisher,
    ResearchExecutionVerifierArtifactPublisher,
)
from .method_runtime import (
    standard_method_evidence_factory,
    standard_method_runtime_binder,
)
from .method_agent_panel import PooledMethodAgentPanelExecution
from .model_requests import build_model_request_recorder
from .research_child_machine_runtime import compose_program_method_runtime_inventory
from .participant_workload import (
    ParticipantMethodRuntime,
    ScheduledParticipantWorkloadBinding,
)
from .research_method_participant_binding import (
    exact_method_programs,
    resolve_exact_method_participant,
)
from .research_os_experiment_runtime_binding import (
    ResearchOSExperimentAggregationRegistry,
    ResearchOSExperimentReconciliationRegistry,
    ResearchOSExperimentReconciliationRegistration,
    ResearchOSExperimentRuntimeComponents,
)
from .research_os_study_closure import materialize_research_protocol_definition
from .research_os_lowering import ImportResearchImplementationResolver
from .research_os_reconciliation import (
    ResearchOSNodeReconciliationProof,
    ResearchOSReconciliationIndeterminate,
)
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphReconciliationDisposition,
)
from .method_telemetry_sink import RawLakeMethodObservationSink
from .model_raw_observation import RawLakeModelEndpointObserver
from .experiment_observation import RawLakeStudyTrialObservationSink
from .research_os_experiment_trial_execution import (
    ResearchOSExperimentTrialProviderBinding,
    ResearchOSExperimentTrialStudyExecutionResolver,
)
from .environment_capability_runtime import (
    AssignmentLifetimeFinalizingTrialProvider,
    compose_local_environment_capability_runtime,
)
from .research_portfolio_execution import (
    ResearchExecutionAuthorities,
    ResearchExecutionAuthorityMaterializerPort,
    ResearchExecutionContext,
)


@dataclass(frozen=True, slots=True)
class PortfolioMethodParticipantResolver:
    """Participant-owner projection over the exact Method IR in the owning program."""

    manifests: PortfolioDerivedProjectManifestResolver

    def resolve(
        self,
        requirement: ResearchParticipantRequirement,
        context: ResearchBindingResolutionContext,
    ):
        return resolve_exact_method_participant(
            self.manifests.program_for(context.definition),
            requirement,
            context.resolution.project_subject,
        )


_AUTO_WORKLOAD_PROVIDER = "noetrium.auto.workload"


def _missing_binding(
    *,
    owner: str,
    subject: CompositionSubject,
    requirement_digest: str,
    code: str,
    summary: str,
    provider_identity: str | None = None,
) -> BindingResolution:
    return BindingResolution.diagnosed(
        (
            BindingDiagnostic(
                code=BindingDiagnosticCode(code),
                severity=BindingDiagnosticSeverity.ERROR,
                blocking=True,
                owner=CompositionSubject.system_subject(SystemIdentity(owner)),
                subject=subject,
                requirement_digest=Sha256Digest(requirement_digest),
                summary=summary,
                provider_identity=provider_identity,
                remediation=BindingRemediationCategory.OWNER_ACTION,
            ),
        )
    )


@dataclass(frozen=True, slots=True)
class PortfolioCapabilityOwnerResolver:
    """Resolve Study capability proofs from platform-owned local authorities."""

    models: "PortfolioQualifiedModelResolver"

    def resolve(
        self,
        requirement: ProjectCapabilityRequirement,
        context: ResearchBindingResolutionContext,
    ) -> tuple[BindingResolution[object], ...]:
        if type(requirement) is not ProjectCapabilityRequirement:
            raise TypeError(
                "local capability resolver requires ProjectCapabilityRequirement"
            )
        requirement_digest = canonical_digest(requirement)
        trial_id = (
            context.definition.binding_requirements.trial_provider_requirement_id
        )
        if requirement.requirement_id == trial_id:
            profile_digest = canonical_digest(
                {
                    "schema": "noetrium.workload-trial-provider.v1",
                    "provider": _AUTO_WORKLOAD_PROVIDER,
                }
            )
            proof = BindingProof(
                owner=CompositionSubject.system_subject(
                    SystemIdentity("experimentation")
                ),
                subject=context.resolution.project_subject,
                requirement_digest=Sha256Digest(requirement_digest),
                provider_identity=_AUTO_WORKLOAD_PROVIDER,
                provider_profile_digest=Sha256Digest(profile_digest),
                binding_generation=(
                    "workload-trial-"
                    + context.definition.definition_digest[:16]
                ),
            )
            return (
                BindingResolution.bound(
                    {"provider": _AUTO_WORKLOAD_PROVIDER},
                    proof,
                ),
            )

        if requirement.requirement_id == "environment.act":
            program = self.models.manifests.program_for(context.definition)
            environments = tuple(
                row
                for row in program.definitions
                if row.kind is ResearchDefinitionKind.ENVIRONMENT
                and isinstance(row.config, Mapping)
                and row.config.get("required_capability") == requirement.requirement_id
            )
            if len(environments) != 1:
                return (
                    _missing_binding(
                        owner="environment",
                        subject=context.resolution.project_subject,
                        requirement_digest=requirement_digest,
                        code="environment.runtime_unavailable",
                        summary=(
                            "ResearchProgram must contain exactly one frozen Environment "
                            "definition exporting environment.act"
                        ),
                    ),
                )
            environment = environments[0]
            profile_digest = canonical_digest({
                "schema": "noetrium.environment-capability-binding.v1",
                "definition_digest": environment.definition_digest,
                "capability_id": requirement.requirement_id,
            })
            proof = BindingProof(
                owner=CompositionSubject.system_subject(SystemIdentity("environment")),
                subject=context.resolution.project_subject,
                requirement_digest=Sha256Digest(requirement_digest),
                provider_identity="noetrium.environment",
                provider_profile_digest=Sha256Digest(profile_digest),
                binding_generation="environment-" + environment.definition_digest[:16],
            )
            return (BindingResolution.bound(environment, proof),)

        model_requirement = next(
            (
                row
                for row in context.definition.binding_requirements.model_roles
                if row.requirement_id == requirement.requirement_id
            ),
            None,
        )
        if model_requirement is not None:
            rows = self.models.resolve(model_requirement, context)
            projected: list[BindingResolution[object]] = []
            for row in rows:
                if row.binding is None:
                    projected.append(row)
                    continue
                binding = row.binding
                proof = BindingProof(
                    owner=CompositionSubject.system_subject(
                        SystemIdentity("model")
                    ),
                    subject=context.resolution.project_subject,
                    requirement_digest=Sha256Digest(requirement_digest),
                    provider_identity=binding.provider_id,
                    provider_profile_digest=Sha256Digest(
                        binding.provider_profile_digest
                    ),
                    binding_generation=(
                        "model-capability-"
                        + binding.deployment_generation[:16]
                    ),
                )
                projected.append(BindingResolution.bound(binding, proof))
            return tuple(projected)

        return (
            _missing_binding(
                owner=(
                    requirement.namespace
                    if requirement.namespace in {
                        "artifact",
                        "data",
                        "environment",
                        "execution",
                        "experimentation",
                        "model",
                        "participant",
                        "resource",
                        "runtime",
                    }
                    else "execution"
                ),
                subject=context.resolution.project_subject,
                requirement_digest=requirement_digest,
                code="runtime.capability_unavailable",
                summary=(
                    "No local provider can satisfy required capability "
                    f"{requirement.requirement_id!r}. Define the capability's "
                    "actual research semantics; no authority configuration is needed."
                ),
            ),
        )


@dataclass(frozen=True, slots=True)
class PortfolioQualifiedModelResolver:
    """Resolve only proof-backed qualified model facts for scientific execution."""

    manifests: PortfolioDerivedProjectManifestResolver
    authority_root: Path
    execution: ResearchExecutionContext
    _method_router_lock: object = field(
        default_factory=RLock, init=False, repr=False, compare=False
    )
    _method_routers: dict[str, MethodAgentLoopRouter | None] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _tokenization_cache_lock: object = field(
        default_factory=RLock, init=False, repr=False, compare=False
    )
    _tokenization_caches: dict[str, ExactModelTokenizationCache] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _model_raw_observer: RawLakeModelEndpointObserver = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        root = Path(self.authority_root).expanduser().absolute()
        if root.exists() and (root.is_symlink() or not root.is_dir()):
            raise ValueError("qualified model authority root must be a real directory")
        object.__setattr__(self, "authority_root", root)
        object.__setattr__(
            self,
            "_model_raw_observer",
            RawLakeModelEndpointObserver(
                self.execution.runtime.observability.raw
            ),
        )



    def _tokenization_cache(
        self,
        binding,
    ) -> ExactModelTokenizationCache:
        identity_digest = canonical_digest({
            "model": binding.model,
            "model_stack_digest": binding.model_stack_digest,
            "tokenizer_sha256": binding.tokenizer_sha256,
            "chat_template_sha256": binding.chat_template_sha256,
        })
        with self._tokenization_cache_lock:
            cache = self._tokenization_caches.get(identity_digest)
            if cache is None:
                cache = ExactModelTokenizationCache(4096)
                self._tokenization_caches[identity_digest] = cache
            return cache

    def _tokenization_for(self, binding):
        return QualifiedEndpointTokenizationProvider(
            binding,
            transport=self.execution.execution_pool.model_json_http_client,
            cache=self._tokenization_cache(binding),
        ).bind(
            model=binding.model,
            model_stack_digest=binding.model_stack_digest,
            tokenizer_sha256=binding.tokenizer_sha256,
            chat_template_sha256=binding.chat_template_sha256,
        )

    @staticmethod
    def _definition(program, definition_id: str, kind: ResearchDefinitionKind):
        matches = tuple(
            row
            for row in program.definitions
            if row.definition_id == definition_id and row.kind is kind
        )
        if len(matches) != 1:
            raise LookupError(
                f"ResearchProgram has no unique {kind.value} definition "
                f"for {definition_id!r}"
            )
        return matches[0]

    def _qualified_bindings(
        self,
        requirement: ResearchModelRoleRequirement,
        context: ResearchBindingResolutionContext,
    ):
        program = self.manifests.program_for(context.definition)
        semantics = research_model_requirement_semantics(program, requirement)
        required_models = semantics.required_models
        prompt_definition = semantics.prompt_definition
        prompt_config = semantics.prompt_config
        prompt_generation_id = semantics.prompt_generation_id

        discovered = []
        root = self.authority_root / "models"
        for path in tuple(sorted(root.glob("*/qualified-model-closure.json"))):
            try:
                closure = load_qualified_model_deployment_closure(
                    path,
                    runtime_qualification_store_factory=(
                        DirectoryRuntimeQualificationEvidenceStore
                    ),
                    runtime_canary_store_factory=(
                        DirectoryRuntimeCanaryEvidenceStore
                    ),
                )
            except QualifiedModelClosureReadError:
                # Historical or corrupt candidates remain durable evidence but
                # are not eligible for current strict binding resolution.
                continue
            authority = PersistedQualifiedModelEndpointBinding(closure)
            try:
                binding = authority.binding_for(
                    role=requirement.role,
                    capability_id="generation",
                    input_schema_id="model.generation.request.v1",
                    output_schema_id="model.generation.response.v1",
                    prompt_generation=prompt_generation_id,
                )
            except (KeyError, LookupError, ValueError):
                continue
            discovered.append(
                (
                    binding,
                    prompt_definition,
                    prompt_config,
                    authority,
                    str(path),
                )
            )

        selected = []
        for requested_model in required_models:
            candidates = tuple(
                row
                for row in discovered
                if requested_model
                in {row[0].model.model_id, row[0].model.logical_name}
            )
            if not candidates:
                raise ResearchBindingRequirementMissing(
                    stage="model",
                    requirement_id=f"{requirement.role}:{requested_model}",
                    requirement_digest=requirement.requirement_digest,
                )
            scientific = {
                (
                    row[0].model_stack_digest,
                    row[0].deployment_generation,
                    row[0].model.model_id,
                    row[0].model.revision,
                )
                for row in candidates
            }
            if len(scientific) != 1:
                raise ValueError(
                    f"model panel member {requirement.role!r}/"
                    f"{requested_model!r} resolves multiple scientific "
                    "generations; freeze an exact qualified member"
                )
            chosen = min(candidates, key=lambda row: row[4])
            selected.append(chosen[:4])
        return tuple(selected)

    def _project_model_binding(
        self,
        requirement: ResearchModelRoleRequirement,
        binding,
        prompt_definition,
        prompt_config,
    ) -> ProjectModelBinding:
        required_capabilities = (
            ("structured_output",)
            if bool(prompt_config.get("structured_output", False))
            else ()
        )
        model_requirement = ModelCapabilityRequirement(
            role=requirement.role,
            prompt_generation_id=str(
                prompt_config.get(
                    "prompt_generation_id", requirement.prompt_configuration_id
                )
            ),
            prompt_id=str(
                prompt_config.get("prompt_id", requirement.prompt_configuration_id)
            ),
            prompt_digest=prompt_definition.definition_digest,
            required_capabilities=required_capabilities,
            minimum_context_tokens=1,
        )
        profile = ModelProviderProfile(
            "noetrium.qualified-model",
            tuple(sorted({"generation", *required_capabilities})),
        )
        tokenization = self._tokenization_for(binding)
        return ProjectModelBinding(
            requirement_digest=model_requirement.digest(),
            provider_id=profile.provider_id,
            provider_profile_digest=profile.digest(),
            role=requirement.role,
            model=binding.model,
            deployment_id=binding.deployment_id,
            deployment_generation=binding.deployment_generation,
            model_stack_digest=binding.model_stack_digest,
            qualification_certificate_digest=binding.qualification_certificate_digest,
            runtime_qualification_digest=binding.runtime_qualification_digest,
            host_identity_digest=binding.host_identity_digest,
            prompt_generation_id=model_requirement.prompt_generation_id,
            prompt_id=model_requirement.prompt_id,
            prompt_digest=model_requirement.prompt_digest,
            capabilities=profile.capabilities,
            runtime_canary_evidence_digests=binding.runtime_canary_evidence_digests,
            request_tokenization_digest=tokenization.identity.digest(),
        )

    def resolve(
        self,
        requirement: ResearchModelRoleRequirement,
        context: ResearchBindingResolutionContext,
    ):
        try:
            candidates = self._qualified_bindings(requirement, context)
        except ResearchBindingRequirementMissing:
            return (
                _missing_binding(
                    owner="model",
                    subject=context.resolution.project_subject,
                    requirement_digest=requirement.requirement_digest,
                    code="model.qualification_missing",
                    summary=(
                        f"No qualified model deployment closure is available for role "
                        f"{requirement.role!r}."
                    ),
                ),
            )
        owner = CompositionSubject.system_subject(SystemIdentity("model"))
        return tuple(
            project_bound_model_resolution(
                self._project_model_binding(
                    requirement, binding, prompt_definition, prompt_config
                ),
                owner=owner,
                subject=context.resolution.project_subject,
            )
            for binding, prompt_definition, prompt_config, _authority in candidates
        )

    def method_agent_loop_router(
        self,
        closure,
        context: ResearchExecutionContext,
    ) -> MethodAgentLoopRouter | None:
        """Return one shared Method model router per frozen Study closure."""

        key = closure.closure_digest
        lock = self._method_router_lock
        with lock:
            if key in self._method_routers:
                return self._method_routers[key]
            router = self._materialize_method_agent_loop_router(closure, context)
            self._method_routers[key] = router
            return router

    def _materialize_method_agent_loop_router(
        self,
        closure,
        context: ResearchExecutionContext,
    ) -> MethodAgentLoopRouter | None:
        # Materialize every frozen scientific panel member, then expose exactly
        # one role-level loop. Multi-member roles fan out without implicit choice.
        study = closure.definition
        frozen_binding = closure.binding
        manifest = self.manifests.resolve(study)
        resolution = resolve_research_requirements(study, manifest)
        resolution_context = ResearchBindingResolutionContext.create(
            study, manifest, resolution
        )
        if resolution.resolution_digest != closure.resolution.resolution_digest:
            raise RuntimeError(
                "Study model runtime resolution drifted from frozen closure"
            )

        recorder = build_model_request_recorder(
            context.state_root / "model-requests" / closure.closure_digest
        )
        context.execution_pool.register_model_io_resource(recorder)
        panel_execution = PooledMethodAgentPanelExecution(
            context.execution_pool,
            execution_tenant_id=context.execution_tenant_id,
        )
        loops = {}
        for requirement in study.binding_requirements.model_roles:
            if not requirement.usage.affects_execution:
                continue
            frozen_rows = tuple(
                sorted(
                    frozen_binding.model_role_bindings_for(requirement.role),
                    key=lambda row: row.member_index,
                )
            )
            if not frozen_rows:
                if requirement.required:
                    raise RuntimeError(
                        f"required execution model role {requirement.role!r} "
                        "has no frozen binding"
                    )
                continue
            if tuple(row.member_index for row in frozen_rows) != tuple(
                range(len(frozen_rows))
            ):
                raise RuntimeError(
                    f"model panel indexes are not contiguous: "
                    f"role={requirement.role!r}"
                )

            qualified = self._qualified_bindings(
                requirement, resolution_context
            )
            if len(qualified) != len(frozen_rows):
                raise RuntimeError(
                    f"model panel cardinality drifted from frozen Study binding: "
                    f"role={requirement.role!r}"
                )

            member_loops = []
            for frozen_row, qualified_row in zip(
                frozen_rows, qualified, strict=True
            ):
                binding, prompt_definition, prompt_config, authority = qualified_row
                projected = self._project_model_binding(
                    requirement,
                    binding,
                    prompt_definition,
                    prompt_config,
                )
                if projected.digest() != frozen_row.binding.digest():
                    raise RuntimeError(
                        f"qualified model panel binding drifted from frozen Study "
                        f"binding: role={requirement.role!r} "
                        f"member={frozen_row.member_index}"
                    )
                replica_set = authority.replica_set_for(
                    role=requirement.role,
                    capability_id="generation",
                    input_schema_id="model.generation.request.v1",
                    output_schema_id="model.generation.response.v1",
                    prompt_generation=frozen_row.binding.prompt_generation_id,
                )
                generation_options = {
                    key: prompt_config[key]
                    for key in (
                        "response_format",
                        "chat_template_kwargs",
                        "temperature",
                        "top_p",
                        "max_tokens",
                    )
                    if key in prompt_config
                }
                request_factory = MethodViewChatRequestFactory(
                    frozen_row.binding.model.logical_name,
                    generation_options,
                )
                member_agent_id = (
                    f"{requirement.role}#{frozen_row.member_index}"
                )
                pool = context.execution_pool.model_endpoint_pool(
                    replica_set,
                    observers=(self._model_raw_observer,),
                )
                tokenization = self._tokenization_for(binding)
                member_loop = MethodModelAgentLoop(
                    binding=MethodModelEndpointBinding(
                        agent_id=member_agent_id,
                        role=requirement.role,
                        model=frozen_row.binding.model,
                        request_factory_digest=request_factory.digest,
                        member_index=frozen_row.member_index,
                    ),
                    pool=pool,
                    recorder=recorder,
                    request_factory=request_factory,
                    tokenization=tokenization,
                    execution_budget=context.execution_budget,
                )
                member_loops.append(
                    (frozen_row.member_index, member_loop)
                )

            if requirement.role in loops:
                raise RuntimeError(
                    f"duplicate model role runtime identity: "
                    f"{requirement.role!r}"
                )
            if len(member_loops) == 1:
                _, member = member_loops[0]
                loops[requirement.role] = MethodModelAgentLoop(
                    binding=MethodModelEndpointBinding(
                        agent_id=requirement.role,
                        role=requirement.role,
                        model=member.binding.model,
                        request_factory_digest=(
                            member.binding.request_factory_digest
                        ),
                        member_index=0,
                    ),
                    pool=member.pool,
                    recorder=member.recorder,
                    request_factory=member.request_factory,
                    tokenization=member.tokenization,
                    execution_budget=context.execution_budget,
                )
            else:
                loops[requirement.role] = MethodAgentPanelLoop(
                    requirement.role,
                    tuple(member_loops),
                    execution=panel_execution,
                )
        if not loops:
            return None
        return MethodAgentLoopRouter(loops)


class CanonicalWorkloadExperimentReconciliation:
    """Recover only when lower effect authority proves no external effect began."""

    def __init__(
        self,
        protocol_digest: str,
        effect_journal: EffectIntentJournal | None,
    ) -> None:
        if type(protocol_digest) is not str or len(protocol_digest) != 64:
            raise TypeError(
                "canonical workload reconciliation requires protocol digest"
            )
        if effect_journal is not None and not isinstance(
            effect_journal, EffectIntentJournal
        ):
            raise TypeError(
                "canonical workload reconciliation requires EffectIntentJournal"
            )
        self.protocol_digest = protocol_digest
        self.effect_journal = effect_journal
        self.identity_digest = canonical_digest(
            {
                "schema": "noetrium.canonical-workload-reconciliation.v3",
                "protocol_digest": protocol_digest,
                "effect_journal_durability": (
                    None if effect_journal is None else effect_journal.durability
                ),
                "effect_boundary": "prepared-is-may-have-happened",
            }
        )

    def reconcile(
        self,
        closure,
        *,
        machine_id,
        execution_cut_id,
        graph_node_id,
        semantic_digest,
        lowering_digest,
        attempt_id,
    ):
        del machine_id
        observed_protocol = closure.research_plan.trial_protocol_identity.digest()
        if observed_protocol != self.protocol_digest:
            raise ValueError(
                "canonical workload reconciliation protocol identity drifted"
            )
        if self.effect_journal is None:
            raise ResearchOSReconciliationIndeterminate(
                "automatic workload Experiment has no effect authority proving "
                "whether its uncertain attempt crossed the external-effect boundary"
            )
        execution_attempt_id = canonical_digest(
            {
                "schema": "noetrium.research-node-attempt.v1",
                "execution_cut_id": execution_cut_id,
                "graph_node_id": graph_node_id,
                "attempt_id": attempt_id,
            }
        )
        effect_records = self.effect_journal.records_for_run(execution_attempt_id)
        if effect_records:
            raise ResearchOSReconciliationIndeterminate(
                "automatic workload Experiment crossed the durable effect-intent "
                "boundary; reconcile lower Effect authority before retry: "
                f"count={len(effect_records)}"
            )
        empty_effect_proof = canonical_digest(
            {
                "schema": "noetrium.effect-intent-run-empty-proof.v1",
                "run_id": execution_attempt_id,
                "journal_durability": self.effect_journal.durability,
                "effect_intent_digests": (),
            }
        )
        return ResearchOSNodeReconciliationProof(
            execution_cut_id=execution_cut_id,
            graph_node_id=graph_node_id,
            semantic_digest=semantic_digest,
            lowering_digest=lowering_digest,
            attempt_id=attempt_id,
            disposition=ResearchGraphReconciliationDisposition.RETRY,
            authority_id="canonical-workload-effect-boundary",
            evidence_digests=(empty_effect_proof, self.identity_digest),
        )

def _exact_program_definition(program, definition_id: str, kind: ResearchDefinitionKind):
    matches = tuple(
        row for row in program.definitions
        if row.definition_id == definition_id and row.kind is kind
    )
    if len(matches) != 1:
        raise ResearchBindingRequirementMissing(
            stage=kind.value,
            requirement_id=definition_id,
            requirement_digest=canonical_digest({
                "definition_id": definition_id,
                "kind": kind.value,
            }),
        )
    return matches[0]


def _materialize_trial_task_projection(
    program,
    study,
    context: ResearchExecutionContext,
    definition_bindings: ResearchDefinitionBindingRegistry,
):
    selected = study.benchmark.selected_tasks(study.benchmark_split_id)
    if not any(row.content is None and row.content_reference is not None for row in selected):
        return TaskDefinitionExperimentTaskProjection()

    benchmark_matches = tuple(
        row
        for row in program.definitions
        if row.kind is ResearchDefinitionKind.BENCHMARK
        and isinstance(row.config, Mapping)
        and row.config.get("benchmark_id") == study.benchmark.benchmark_id
    )
    if len(benchmark_matches) != 1:
        raise ResearchBindingRequirementMissing(
            stage="benchmark",
            requirement_id=study.benchmark.benchmark_id,
            requirement_digest=study.benchmark.benchmark_digest,
        )
    definition = benchmark_matches[0]
    if definition.implementation is None:
        bound = definition_bindings.resolve(definition).binding
        if isinstance(bound, TrialTaskProjectionPort):
            projection = bound
        else:
            factory = getattr(bound, "task_projection", None)
            if not callable(factory):
                raise TypeError(
                    "platform BENCHMARK binding with content references must "
                    "provide TrialTaskProjectionPort or task_projection()"
                )
            projection = factory(study, content=context.content)
    else:
        factory = ImportResearchImplementationResolver().resolve(
            definition
        ).implementation
        projection = factory(study, content=context.content)
    if not isinstance(projection, TrialTaskProjectionPort):
        raise TypeError(
            "BENCHMARK execution factory must return TrialTaskProjectionPort"
        )
    identity = getattr(projection, "identity_digest", None)
    if type(identity) is not str or len(identity) != 64:
        raise TypeError(
            "BENCHMARK task projection identity_digest must be SHA-256"
        )
    return projection


def _materialize_trial_verifier(
    program,
    study,
    context: ResearchExecutionContext,
    definition_bindings: ResearchDefinitionBindingRegistry,
):
    verifier_ids = tuple(sorted({
        package.verifier_requirement_id
        for task in study.benchmark.selected_tasks(study.benchmark_split_id)
        if (package := task.package) is not None
        and package.verifier_requirement_id is not None
    }))
    if not verifier_ids:
        return None, None
    if len(verifier_ids) != 1:
        raise ValueError(
            "one Trial verifier authority must be explicit per verifier requirement; "
            f"selected={verifier_ids!r}"
        )
    definition = _exact_program_definition(
        program,
        verifier_ids[0],
        ResearchDefinitionKind.VERIFIER,
    )
    if definition.implementation is None:
        verifier = definition_bindings.resolve(definition).binding
    else:
        factory = ImportResearchImplementationResolver().resolve(
            definition
        ).implementation
        verifier = factory(study, content=context.content)
    if not callable(getattr(verifier, "verify", None)):
        raise TypeError("VERIFIER factory must return TaskVerifierPort")
    identity = getattr(verifier, "identity_digest", None)
    if type(identity) is not str or len(identity) != 64:
        raise TypeError("TaskVerifier authority_digest must be SHA-256")
    return verifier, identity


@dataclass(frozen=True, slots=True)
class PortfolioAutomaticTrialProviderResolver:
    """Build the canonical workload TrialProvider directly from frozen Study IR."""

    manifests: PortfolioDerivedProjectManifestResolver
    context: ResearchExecutionContext
    runtime_inventory: MethodRuntimePortInventory
    model_resolver: PortfolioQualifiedModelResolver
    definition_bindings: ResearchDefinitionBindingRegistry
    lifetime_releaser: object | None = None
    program_journal: DirectoryMachineJournal | None = None

    def resolve(self, closure) -> ResearchOSExperimentTrialProviderBinding:
        provider_ids = {
            row.provider_id
            for row in closure.research_plan.experiment_plan.bindings
        }
        if provider_ids != {_AUTO_WORKLOAD_PROVIDER}:
            raise LookupError(
                "Study selected a non-canonical Trial provider; declare its "
                "research semantics in the ResearchProgram"
            )
        program = self.manifests.program_for(closure.definition)
        requirements = closure.definition.binding_requirements.participants
        if not requirements:
            raise RuntimeError(
                "automatic workload Trial execution requires at least one participant"
            )
        schedule = closure.research_plan.participant_schedule
        if schedule is None:
            raise RuntimeError(
                "participant execution requires the frozen participant schedule"
            )
        exact_methods = exact_method_programs(program)
        study_inventory = MethodRuntimePortInventory(
            agent_loop=self.model_resolver.method_agent_loop_router(
                closure,
                self.context,
            ),
            capabilities=self.runtime_inventory.capabilities,
            child_machines=self.runtime_inventory.child_machines,
            schemas=self.runtime_inventory.schemas,
        )
        program_journal = self.program_journal
        if program_journal is None:
            raise RuntimeError(
                "automatic Trial provider requires canonical program journal authority"
            )
        participant_runtimes = []
        method_inventories: dict[str, MethodRuntimePortInventory] = {}
        for requirement in requirements:
            method = exact_methods.get(requirement.method_id)
            if method is None:
                raise LookupError(
                    f"Study has no frozen MethodProgram for {requirement.method_id!r}"
                )
            program_inventory = method_inventories.get(method.program_digest)
            if program_inventory is None:
                program_inventory = compose_program_method_runtime_inventory(
                    program,
                    study_inventory,
                    method_program_digests=(method.program_digest,),
                    journal=program_journal,
                    max_steps=10_000,
                )
                method_inventories[method.program_digest] = program_inventory
            runtime = compose_method_runtime_bindings(
                method,
                program_inventory,
                runtime_binder=standard_method_runtime_binder(),
                evidence_factory=standard_method_evidence_factory(
                    self.context.content
                ),
                dispatcher=self.context.runtime.operation_runtime.dispatcher,
                observation=RawLakeMethodObservationSink(
                    self.context.runtime.observability.raw
                ),
                execution_budget=self.context.execution_budget,
                state_root=(
                    self.context.state_root
                    / "method-workloads"
                    / closure.closure_digest
                    / requirement.role
                ),
            )
            participant_runtimes.append(
                ParticipantMethodRuntime(
                    requirement.role,
                    requirement.participant_kind,
                    requirement.treatment_id,
                    method,
                    runtime,
                )
            )
        workload = bind_workload_graph(
            ScheduledParticipantWorkloadBinding(
                schedule=schedule,
                participants=tuple(participant_runtimes),
                journal=program_journal,
                execution_pool=self.context.execution_pool,
            ),
            journal=program_journal,
        )
        task_projection = _materialize_trial_task_projection(
            program,
            closure.definition,
            self.context,
            self.definition_bindings,
        )
        verifier, verifier_identity_digest = _materialize_trial_verifier(
            program,
            closure.definition,
            self.context,
            self.definition_bindings,
        )
        provider = WorkloadTrialProvider(
            protocol_identity=closure.research_plan.trial_protocol_identity,
            workload=workload,
            task_projection=task_projection,
            measurement_projection=StandardWorkloadMeasurementProjection(),
            execution_budget=self.context.execution_budget,
            artifact_publisher=(
                None
                if verifier is None
                else ResearchExecutionVerifierArtifactPublisher(self.context.content)
            ),
        )
        lifetime_releaser = self.lifetime_releaser
        if lifetime_releaser is not None:
            selector = getattr(lifetime_releaser, "for_program", None)
            if callable(selector):
                lifetime_releaser = selector(program.program_id)
        if lifetime_releaser is not None:
            provider = AssignmentLifetimeFinalizingTrialProvider(
                provider,
                lifetime_releaser,
            )
        return ResearchOSExperimentTrialProviderBinding(
            _AUTO_WORKLOAD_PROVIDER,
            provider,
            provider.identity_digest,
            verifier,
            verifier_identity_digest,
        )


def _model_physical_owner_digest(binding: ProjectModelBinding) -> str:
    if not isinstance(binding, ProjectModelBinding):
        raise TypeError("model physical owner projection requires ProjectModelBinding")
    return canonical_digest(
        {
            "schema": "noetrium.model-physical-owner.v1",
            "provider_id": binding.provider_id,
            "model": binding.model,
            "deployment_id": binding.deployment_id,
            "deployment_generation": binding.deployment_generation,
            "model_stack_digest": binding.model_stack_digest,
            "qualification_certificate_digest": (
                binding.qualification_certificate_digest
            ),
            "runtime_qualification_digest": binding.runtime_qualification_digest,
            "host_identity_digest": binding.host_identity_digest,
            "runtime_canary_evidence_digests": tuple(
                sorted(binding.runtime_canary_evidence_digests)
            ),
        }
    )


def _model_definition_owner_identity(
    bindings: tuple[ProjectModelBinding, ...],
) -> str:
    if type(bindings) is not tuple or not bindings:
        raise TypeError("model definition owner identity requires non-empty tuple")
    physical = tuple(
        sorted({_model_physical_owner_digest(row) for row in bindings})
    )
    return canonical_digest(
        {
            "schema": "noetrium.model-definition-owner.v1",
            "physical_owner_digests": physical,
        }
    )


def _materialize_platform_definition_bindings(
    portfolio: ResearchPortfolio,
    *,
    context: ResearchExecutionContext,
    manifests: PortfolioDerivedProjectManifestResolver,
    research_bindings: ResearchBindingAuthority,
    environment_runtime,
) -> ResearchDefinitionBindingRegistry:
    rows: dict[str, ResearchDefinitionBinding] = {}
    studies: list[tuple[object, object]] = []
    model_definition_bindings: dict[
        str, tuple[object, dict[str, object]]
    ] = {}

    def add(definition, *, owner: str, provider: str, identity: str, binding: object) -> None:
        candidate = ResearchDefinitionBinding(
            definition.definition_id,
            definition.kind,
            definition.definition_digest,
            owner,
            provider,
            identity,
            binding,
        )
        previous = rows.get(definition.definition_digest)
        if previous is not None and previous.binding_digest != candidate.binding_digest:
            raise RuntimeError(
                "one platform ResearchDefinition resolved to multiple owner bindings: "
                f"{definition.definition_id}"
            )
        rows[definition.definition_digest] = candidate

    environment_by_program = (
        {}
        if environment_runtime is None
        else dict(environment_runtime.runtimes)
    )

    for program in portfolio.programs:
        for definition in program.definitions:
            if definition.kind is ResearchDefinitionKind.PROTOCOL:
                study = None
                if definition.implementation is not None:
                    study = materialize_research_protocol_definition(definition)
                else:
                    config = thaw_json(definition.config)
                    if isinstance(config, Mapping):
                        candidate = config.get("study", config)
                        try:
                            study = materialize_research_study_spec(candidate)
                        except (KeyError, TypeError, ValueError):
                            study = None
                        if study is not None:
                            add(
                                definition,
                                owner="experimentation",
                                provider="experimentation.study-protocol",
                                identity=study.definition_digest,
                                binding=study,
                            )
                if study is not None:
                    studies.append((program, study))
                continue

            if not definition.platform_resolved:
                continue

            if definition.kind is ResearchDefinitionKind.CONFIGURATION:
                add(
                    definition,
                    owner="research-os",
                    provider="research-os.immutable-configuration",
                    identity=definition.definition_digest,
                    binding=definition.config,
                )
                continue

            if definition.kind is ResearchDefinitionKind.ENVIRONMENT:
                runtime = environment_by_program.get(program.program_id)
                if (
                    runtime is not None
                    and runtime.definition_digest == definition.definition_digest
                ):
                    add(
                        definition,
                        owner="environment",
                        provider=runtime.implementation_id,
                        identity=canonical_digest(
                            {
                                "definition_digest": runtime.definition_digest,
                                "implementation_id": runtime.implementation_id,
                                "port": runtime.port.identity_digest,
                                "lifetime": runtime.lifetime.identity_digest,
                            }
                        ),
                        binding=runtime,
                    )
                continue

            if definition.kind is ResearchDefinitionKind.DATASET:
                config = thaw_json(definition.config)
                if not isinstance(config, Mapping):
                    continue
                dataset_id = config.get("dataset_id", definition.definition_id)
                version = config.get("version")
                if type(dataset_id) is not str or type(version) is not str:
                    continue
                try:
                    dataset = context.management.platform_meta.datasets.get(
                        DatasetIdentity(dataset_id, version)
                    )
                except (KeyError, LookupError):
                    continue
                add(
                    definition,
                    owner="data",
                    provider="platform-meta.dataset-registry",
                    identity=canonical_digest(dataset),
                    binding=dataset,
                )
                continue

            if definition.kind is ResearchDefinitionKind.RESOURCE_POLICY:
                config = thaw_json(definition.config)
                actual = asdict(context.execution_pool.resource_competition_policy)
                if isinstance(config, Mapping) and dict(config) == actual:
                    add(
                        definition,
                        owner="resource",
                        provider="research-execution-pool.resource-competition",
                        identity=context.execution_pool.resource_competition_policy_digest,
                        binding=context.execution_pool.resource_competition_policy,
                    )
                continue

    for program, study in studies:
        try:
            _resolution, contribution = research_bindings.resolve(study)
        except ResearchBindingRequirementMissing:
            continue

        for requirement in study.binding_requirements.model_roles:
            definitions = tuple(
                row
                for row in program.definitions
                if row.platform_resolved
                and row.kind is ResearchDefinitionKind.MODEL
                and row.definition_id == requirement.requirement_id
            )
            bound = contribution.model_role_bindings_for(requirement.role)
            if len(definitions) == 1 and bound:
                definition = definitions[0]
                existing = model_definition_bindings.get(
                    definition.definition_digest
                )
                if existing is None:
                    by_binding_digest: dict[str, object] = {}
                    model_definition_bindings[definition.definition_digest] = (
                        definition,
                        by_binding_digest,
                    )
                else:
                    existing_definition, by_binding_digest = existing
                    if (
                        existing_definition.definition_digest
                        != definition.definition_digest
                    ):
                        raise RuntimeError(
                            "model definition owner aggregation identity drift"
                        )
                for row in bound:
                    by_binding_digest[row.binding_digest] = row

        for participant in contribution.participant_bindings:
            definitions = tuple(
                row
                for row in program.definitions
                if row.platform_resolved
                and row.kind is ResearchDefinitionKind.PARTICIPANT
                and (
                    row.definition_id == participant.role
                    or (
                        isinstance(row.config, Mapping)
                        and row.config.get("role") == participant.role
                    )
                )
            )
            if len(definitions) == 1:
                add(
                    definitions[0],
                    owner="participant",
                    provider=participant.binding.provider_id,
                    identity=participant.binding_digest,
                    binding=participant,
                )

        benchmark_definitions = tuple(
            row
            for row in program.definitions
            if row.platform_resolved
            and row.kind is ResearchDefinitionKind.BENCHMARK
            and (
                row.definition_id == study.benchmark.benchmark_id
                or (
                    isinstance(row.config, Mapping)
                    and row.config.get("benchmark_id")
                    == study.benchmark.benchmark_id
                )
            )
        )
        if len(benchmark_definitions) == 1:
            add(
                benchmark_definitions[0],
                owner="experimentation",
                provider="experimentation.benchmark-cut",
                identity=study.benchmark.cut_digest,
                binding=study.benchmark,
            )

    for definition_digest in sorted(model_definition_bindings):
        definition, by_binding_digest = model_definition_bindings[definition_digest]
        role_bindings = tuple(
            by_binding_digest[key] for key in sorted(by_binding_digest)
        )
        physical_bindings = tuple(row.binding for row in role_bindings)
        add(
            definition,
            owner="model",
            provider="qualified-model-binding",
            identity=_model_definition_owner_identity(physical_bindings),
            binding=role_bindings,
        )

    return ResearchDefinitionBindingRegistry(tuple(rows.values()))


@dataclass(frozen=True, slots=True)
class LocalResearchExecutionAuthorityMaterializer:
    """Canonical local materializer for every ResearchPortfolio cardinality.

    This class owns composition only. Model, Environment, Capability and Trial
    facts stay with their owner systems; later resolver components plug into this
    one root rather than creating project-specific execution paths.
    """

    context: ResearchExecutionContext
    project_manifest: ProjectManifest

    def __post_init__(self) -> None:
        if type(self.context) is not ResearchExecutionContext:
            raise TypeError("local research authority materializer requires ResearchExecutionContext")
        if not isinstance(self.project_manifest, ProjectManifest):
            raise TypeError("local research authority materializer requires ProjectManifest")

    def materialize(self, portfolio: ResearchPortfolio) -> ResearchExecutionAuthorities:
        if type(portfolio) is not ResearchPortfolio:
            raise TypeError("local research authority materializer requires ResearchPortfolio")

        manifests = PortfolioDerivedProjectManifestResolver(
            self.project_manifest,
            portfolio.programs,
        )
        runtime_requirements: dict[
            tuple[str, str], set[str]
        ] = {}
        for program in portfolio.programs:
            for definition in program.definitions:
                if definition.kind is not ResearchDefinitionKind.PROTOCOL:
                    continue
                study = materialize_research_protocol_definition(definition)
                for requirement in study.binding_requirements.model_roles:
                    semantics = research_model_requirement_semantics(
                        program,
                        requirement,
                    )
                    capabilities = {"generation"}
                    if (
                        semantics.structured_output
                        or bool(
                            semantics.prompt_config.get(
                                "structured_output",
                                False,
                            )
                        )
                    ):
                        capabilities.add("structured_output")
                    for model_id in semantics.required_models:
                        runtime_requirements.setdefault(
                            (model_id, requirement.role),
                            set(),
                        ).update(capabilities)
        required_models = tuple(
            RequiredModelRuntime(
                model_id=model_id,
                role=role,
                required_capabilities=tuple(sorted(capabilities)),
            )
            for (model_id, role), capabilities
            in sorted(runtime_requirements.items())
        )
        if required_models:
            replica_pool = self.context.model_replica_pool
            if replica_pool is None:
                raise RuntimeError(
                    "required model runtime refresh requires model replica pool"
                )
            refresh_required_qualified_model_runtimes(
                authority_root=self.context.state_root / "authorities",
                project_root=self.context.state_root.parents[1],
                required_models=required_models,
                assets=self.context.management.models.assets,
                compute_scheduler=(
                    self.context.management.compute_scheduler
                ),
                model_resources=self.context.management.models.resources,
                state_root=(
                    self.context.management.durable_directories.layout.root(ManagedDirectoryKind.STATE)
                    / "model"
                ),
                runtime_workdir=(
                    self.context.management.physical_directories.layout.root(ManagedDirectoryKind.STATE)
                    / "model"
                    / "runtime-workdir"
                ),
                model_replica_pool=replica_pool,
                deployment_runtime=(
                    self.context.management.models.deployment_runtime
                ),
                compute_inventory=(
                    self.context.management.platform_meta.compute_inventory
                ),
                execution_pool=self.context.execution_pool,
            )
        model_resolver = PortfolioQualifiedModelResolver(
            manifests,
            self.context.state_root / "authorities",
            self.context,
        )
        research_bindings = ResearchBindingAuthority(
            manifests,
            PortfolioCapabilityOwnerResolver(model_resolver),
            PortfolioMethodParticipantResolver(manifests),
            model_resolver,
        )

        environment_runtime = compose_local_environment_capability_runtime(
            portfolio,
            self.context,
        )
        environment_effect_journals = (
            {}
            if environment_runtime is None
            else {
                program_id: runtime.effect_journal
                for program_id, runtime in environment_runtime.runtimes
            }
        )
        runtime_inventory = MethodRuntimePortInventory(
            capabilities=(
                None if environment_runtime is None else environment_runtime.port
            ),
        )
        definition_bindings = _materialize_platform_definition_bindings(
            portfolio,
            context=self.context,
            manifests=manifests,
            research_bindings=research_bindings,
            environment_runtime=environment_runtime,
        )
        program_journal = DirectoryMachineJournal(
            self.context.state_root / "machine-state" / "program-journal"
        )
        trial_providers = PortfolioAutomaticTrialProviderResolver(
            manifests,
            self.context,
            runtime_inventory,
            model_resolver,
            definition_bindings,
            None if environment_runtime is None else environment_runtime.lifetime,
            program_journal,
        )
        reconciliation_registrations = []
        seen_protocols = set()
        for program in portfolio.programs:
            for definition in program.definitions:
                if definition.kind is ResearchDefinitionKind.PROTOCOL:
                    study = materialize_research_protocol_definition(
                        definition,
                        definition_bindings=definition_bindings,
                    )
                    protocol_digest = study.trial_protocol_identity.digest()
                    if protocol_digest in seen_protocols:
                        continue
                    seen_protocols.add(protocol_digest)
                    reconciliation_registrations.append(
                        ResearchOSExperimentReconciliationRegistration(
                            _AUTO_WORKLOAD_PROVIDER,
                            protocol_digest,
                            CanonicalWorkloadExperimentReconciliation(
                                protocol_digest,
                                environment_effect_journals.get(program.program_id),
                            ),
                        )
                    )
        runtime_components = ResearchOSExperimentRuntimeComponents(
            study_execution=ResearchOSExperimentTrialStudyExecutionResolver(
                trial_providers,
                observation=RawLakeStudyTrialObservationSink(
                    self.context.runtime.observability.raw
                ),
                receipt_publisher=ResearchExecutionTrialReceiptPublisher(
                    self.context.content
                ),
            ),
            aggregation=ResearchOSExperimentAggregationRegistry.canonical(),
            reconciliation=ResearchOSExperimentReconciliationRegistry(
                tuple(reconciliation_registrations)
            ),
        )
        authority_manifest_digest = canonical_digest(
            {
                "schema": "noetrium.local-research-execution-authorities.v1",
                "portfolio_digest": portfolio.portfolio_digest,
                "project_manifest_digest": self.project_manifest.semantic_digest,
                "definition_bindings": definition_bindings.identity_digest,
            }
        )
        return ResearchExecutionAuthorities.from_study_bindings(
            authority_manifest_digest,
            research_bindings=research_bindings,
            experiment_runtime_components=runtime_components,
            method_runtime_inventory=runtime_inventory,
            definition_bindings=definition_bindings,
            owned_runtime_resources=(
                () if environment_runtime is None else (environment_runtime,)
            ),
        )


def build_local_research_execution_authority_materializer(
    context: ResearchExecutionContext,
    project_manifest: ProjectManifest,
) -> ResearchExecutionAuthorityMaterializerPort:
    materializer = LocalResearchExecutionAuthorityMaterializer(
        context,
        project_manifest,
    )
    if not isinstance(materializer, ResearchExecutionAuthorityMaterializerPort):
        raise TypeError("default local materializer does not satisfy execution authority port")
    return materializer


__all__ = [
    "LocalResearchExecutionAuthorityMaterializer",
    "PortfolioMethodParticipantResolver",
    "PortfolioQualifiedModelResolver",
    "build_local_research_execution_authority_materializer",
]

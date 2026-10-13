from __future__ import annotations
from noetrium_platform.research.experimentation.api.research_compiler import research_plan_study, research_plan_protocol, research_plan_value, research_plan_digest, compile_research_participant_schedule, research_plan_study_identity, research_plan_trial_protocol_identity
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    study_plan_provider_id,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.trial import (
    TrialExecutionRequest,
    TrialExecutionReceipt,
    TrialExecutionStageReceipt,
    TrialPreparationPort,
    TrialProviderPort,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    ExecutionControlPort,
    SingleFlightCache,
)

from collections.abc import Mapping
from functools import partial
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Lock, RLock

from noetrium_platform.capabilities.model.api import (
    ModelProviderProfile,
    ProjectModelBinding,
)
from noetrium_platform.capabilities.model.api.unit_semantics import (
    model_capability_requirement_unit,
)
from noetrium_platform.capabilities.model.composition.binding_resolution import (
    project_bound_model_resolution,
    resolve_qualified_project_binding,
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
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.foundation.kernel.kernel import (
    DirectoryMachineJournal,
    Sha256Digest,
    canonical_digest,
    require_sha256,
    thaw_json,
)
from noetrium_platform.evidence.data.dataset.api import DatasetIdentity
from noetrium_platform.infrastructure.reliability.effect.api import EffectIntentJournal
from noetrium_platform.infrastructure.reliability.forensics.runtime.phase_trace import CausalPhaseTrace
from noetrium_platform.infrastructure.lifecycle.runtime import ResourceLifetimeController
from noetrium_platform.infrastructure.resources.directory.api import ManagedDirectoryKind
from noetrium_platform.foundation.portfolio.api import (
    project_capability_requirement_id,
    project_capability_requirement_namespace,
    project_manifest_digest,
    project_manifest_project_id,
    require_project_capability_requirement,
    require_project_manifest,
)
from noetrium_platform.product.research_unit import require_research_root
from noetrium_platform.product.research_metric_scope import scoped_protocol_metric_symbols
from noetrium_platform.product.research_traits import (
    TRAIT_BENCHMARK,
    TRAIT_CONFIGURATION,
    TRAIT_DATASET,
    TRAIT_ENVIRONMENT,
    TRAIT_MODEL,
    TRAIT_PARTICIPANT,
    TRAIT_PORTFOLIO,
    TRAIT_PROGRAM,
    TRAIT_PROTOCOL,
    TRAIT_VERIFIER,
)
from noetrium_platform.research.experimentation.api import (
    materialize_research_study_spec,
    ResearchBindingContribution,
    compile_experiment_program,
    compile_research_plan,
    binding_requirements_model_roles,
    binding_requirements_participants,
    binding_requirements_trial_provider,
    model_role_requirement_capabilities,
    model_role_requirement_capability,
    model_role_requirement_id,
    model_role_requirement_input_schema,
    model_role_requirement_minimum_context,
    model_role_requirement_output_schema,
    model_role_requirement_prompt,
    model_role_requirement_required,
    model_role_requirement_role,
    model_role_requirement_usage,
    participant_requirement_kind,
    participant_requirement_method_id,
    participant_requirement_role,
    participant_requirement_treatment_id,
    require_model_role_requirement,
    resolve_research_requirements,
)
from noetrium_platform.research.experimentation.lifecycle.study.providers import (
    StandardWorkloadMeasurementProjection,
    WorkloadTrialProvider,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import (
    benchmark_selected_tasks,
    study_benchmark,
    study_benchmark_split_id,
    study_binding_requirements,
    study_definition_digest,
    study_trial_protocol,
    task_package,
)
from noetrium_platform.research.experimentation.workload.composition import (
    bind_workload_graph,
    compose_method_runtime_bindings,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodLifetimeResourcePort,
    method_lifetime_resources,
    MethodRuntimePort,
    MethodRuntimePortInventory,
    analyze_method_runtime_requirements,
)
from noetrium_platform.research.execution.workflow.composition import (
    MethodAgentLoopRouter,
    MethodAgentPanelLoop,
    MethodModelAgentLoop,
    MethodModelEndpointBinding,
    MethodViewChatRequestFactory,
    reserve_method_lifetime_resources,
)
from .research_binding_authority import (
    ResearchBindingAuthority,
    ResearchBindingResolutionContext,
    ResearchCapabilityBindingRegistry,
    ResearchBindingRequirementMissing,
)
from .research_symbol_authority import (
    ResearchSymbolBinding,
    ResearchSymbolBindingRegistry,
)
from .research_execution_manifest import PortfolioDerivedProjectManifestResolver
from .model_runtime_bootstrap import (
    RequiredModelRuntime,
    qualified_model_closure_path,
)
from .model_runtime_refresh import refresh_required_qualified_model_runtimes
from .research_model_requirements import research_model_binding_units
from .research_experiment import require_experiment_execution_binding
from .research_execution_content import (
    ResearchExecutionTrialReceiptPublisher,
    ResearchExecutionVerifierArtifactPublisher,
)
from .method_runtime import (
    standard_method_evidence_factory,
    METHOD_RUNTIME_BINDER_DIGEST,
    bind_standard_method_runtime,
)
from .method_agent_panel import PooledMethodAgentPanelExecution
from .model_requests import build_model_request_recorder
from .research_unit_activation import compose_research_node_method_runtime_inventory
from .method_schema_runtime import compile_method_schema_authority
from .participant_workload import (
    ParticipantMethodBinding,
    ScheduledParticipantWorkloadBinding,
)
from .research_method_participant_binding import (
    exact_method_programs,
    resolve_exact_method_participant,
)
from .research_experiment_runtime_binding import (
    ResearchExperimentReconciliationRegistry,
    ResearchExperimentReconciliationRegistration,
    ResearchExperimentRuntimeBindingAuthority,
)
from .research_study_closure import (
    StudySpecCompiler,
    materialize_platform_research_protocol_binding,
    materialize_research_protocol_definition,
    research_measurement_definitions,
)
from .research_lowering import ImportResearchImplementationResolver
from .research_reconciliation import (
    ResearchNodeReconciliationProof,
    ResearchReconciliationIndeterminate,
)
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphReconciliationDisposition,
)
from .method_telemetry_sink import RawLakeMethodObservationSink
from .model_raw_observation import RawLakeModelEndpointObserver
from .experiment_observation import RawLakeStudyTrialObservationSink
from .diagnostic_degradation import ForensicDiagnosticDegradationSink
from .research_experiment_trial_execution import (
    ResearchExperimentTrialProviderBinding,
    ResearchExperimentTrialStudyExecutionResolver,
)
from .environment_capability_runtime import (
    compose_local_environment_capability_runtime,
    prepare_assignment_environment_trial,
    release_assignment_environment_trial,
)
from .shared_host_pressure import ResourceCompetitionDemand
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
        requirement: NoetriumUnit,
        context: ResearchBindingResolutionContext,
    ):
        program = self.manifests.program_for(context.definition)
        return resolve_exact_method_participant(
            program,
            requirement,
            context.resolution.project_subject,
            method_programs=self.manifests.method_programs_for(program),
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


def _program_environment_requirement_kind(
    environment: NoetriumUnit | None, requirement_id: str
) -> str | None:
    """Classify only exact Program-environment requirements.

    ``environment.act`` is the generic action capability exported by the one
    frozen Environment. A benchmark package may instead require that exact
    Environment definition by Unit ID. No family/name prefix fallback is
    allowed: specialized environment definitions must bind only to an exact ID.
    """
    if requirement_id == "environment.act":
        return "action-capability"
    if environment is not None and requirement_id == environment.unit_id:
        return "environment-definition"
    return None


@dataclass(frozen=True, slots=True)
class PortfolioCapabilityOwnerResolver:
    """Resolve Study capability proofs from platform-owned local authorities."""

    models: "PortfolioQualifiedModelResolver"
    _environment_cache_lock: object = field(
        default_factory=RLock, init=False, repr=False, compare=False
    )
    _environment_by_program: dict[str, NoetriumUnit | None] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def _environment_for_program(self, program: NoetriumUnit) -> NoetriumUnit | None:
        key = program.unit_digest
        with self._environment_cache_lock:
            if key in self._environment_by_program:
                return self._environment_by_program[key]
        environments = tuple(
            row
            for row in program.symbols
            if row.has_trait(TRAIT_ENVIRONMENT)
            and isinstance(row.parameters, Mapping)
            and isinstance(row.parameters.get("capabilities"), (tuple, list))
            and "environment.act" in tuple(row.parameters["capabilities"])
        )
        if len(environments) > 1:
            resolved = None
        else:
            resolved = None if not environments else environments[0]
        with self._environment_cache_lock:
            existing = self._environment_by_program.setdefault(key, resolved)
        if (
            existing is not None
            and resolved is not None
            and existing.symbol_digest != resolved.symbol_digest
        ):
            raise RuntimeError(
                "immutable Program resolved multiple Environment definitions"
            )
        return existing

    def resolve(
        self,
        requirement: NoetriumUnit,
        context: ResearchBindingResolutionContext,
    ) -> tuple[BindingResolution[object], ...]:
        requirement = require_project_capability_requirement(requirement)
        requirement_digest = requirement.unit_digest
        requirement_id = project_capability_requirement_id(requirement)
        requirement_namespace = project_capability_requirement_namespace(requirement)
        trial_id = (
            binding_requirements_trial_provider(study_binding_requirements(context.definition))
        )
        if requirement_id == trial_id:
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
                    + study_definition_digest(context.definition)[:16]
                ),
            )
            return (
                BindingResolution.bound(
                    {"provider": _AUTO_WORKLOAD_PROVIDER},
                    proof,
                ),
            )

        program = self.models.manifests.program_for(context.definition)
        environment = self._environment_for_program(program)
        binding_kind = _program_environment_requirement_kind(
            environment, requirement_id
        )
        if binding_kind is not None:
            if environment is None:
                return (
                    _missing_binding(
                        owner="environment",
                        subject=context.resolution.project_subject,
                        requirement_digest=requirement_digest,
                        code="environment.runtime_unavailable",
                        summary=(
                            "NoetriumUnit must contain exactly one frozen Environment "
                            "definition exporting environment.act"
                        ),
                    ),
                )
            profile_digest = canonical_digest({
                "schema": "noetrium.environment-capability-binding.v2",
                "definition_digest": environment.symbol_digest,
                "requirement_id": requirement_id,
                "binding_kind": binding_kind,
            })
            proof = BindingProof(
                owner=CompositionSubject.system_subject(SystemIdentity("environment")),
                subject=context.resolution.project_subject,
                requirement_digest=Sha256Digest(requirement_digest),
                provider_identity="noetrium.environment",
                provider_profile_digest=Sha256Digest(profile_digest),
                binding_generation="environment-" + environment.symbol_digest[:16],
            )
            return (BindingResolution.bound(environment, proof),)

        model_requirement = next(
            (
                row
                for row in binding_requirements_model_roles(study_binding_requirements(context.definition))
                if model_role_requirement_id(row) == requirement_id
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
                proof = row.proof
                if proof is None:
                    raise RuntimeError(
                        "static model binding lost its proof"
                    )
                capability_proof = BindingProof(
                    owner=proof.owner,
                    subject=context.resolution.project_subject,
                    requirement_digest=Sha256Digest(requirement_digest),
                    provider_identity=proof.provider_identity,
                    provider_profile_digest=proof.provider_profile_digest,
                    binding_generation=(
                        "model-capability-"
                        + proof.provider_profile_digest.value[:16]
                    ),
                )
                projected.append(
                    BindingResolution.bound(row.binding, capability_proof)
                )
            return tuple(projected)

        return (
            _missing_binding(
                owner=(
                    requirement_namespace
                    if requirement_namespace in {
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
                    f"{requirement_id!r}. Define the capability's "
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
    _method_routers: SingleFlightCache[
        tuple[MethodAgentLoopRouter | None]
    ] = field(
        default_factory=SingleFlightCache,
        init=False,
        repr=False,
        compare=False,
    )
    _runtime_refreshes: SingleFlightCache[bool] = field(
        default_factory=SingleFlightCache,
        init=False,
        repr=False,
        compare=False,
    )
    _tokenization_cache_lock: object = field(
        default_factory=RLock, init=False, repr=False, compare=False
    )
    _tokenization_caches: dict[str, ExactModelTokenizationCache] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _model_request_recorder_lock: object = field(
        default_factory=RLock, init=False, repr=False, compare=False
    )
    _model_request_recorders: dict[str, object] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _binding_resolution_lock: object = field(
        default_factory=RLock, init=False, repr=False, compare=False
    )
    _binding_resolutions: dict[
        tuple[str, str, str], tuple[BindingResolution[NoetriumUnit], ...]
    ] = field(default_factory=dict, init=False, repr=False, compare=False)
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



    def _model_request_recorder(self, context: ResearchExecutionContext):
        state_root = Path(context.state_root).expanduser().absolute()
        key = str(state_root)
        with self._model_request_recorder_lock:
            recorder = self._model_request_recorders.get(key)
            if recorder is not None:
                return recorder
            recorder = build_model_request_recorder(state_root / "model-requests")
            context.execution_pool.register_model_io_resource(recorder)
            self._model_request_recorders[key] = recorder
            return recorder

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
        tokenization_capacity = binding.preferred_admitted_concurrency
        if tokenization_capacity is None:
            tokenization_capacity = binding.max_admitted_concurrency
        tokenization_generation = canonical_digest({
            "deployment_generation": binding.deployment_generation,
            "resource_domain": "tokenization-frontend",
        })
        admission = self.execution.execution_pool.model_admission.controller_for(
            deployment_id=binding.deployment_id,
            deployment_generation=tokenization_generation,
            qualified_capacity=tokenization_capacity,
        )
        return QualifiedEndpointTokenizationProvider(
            binding,
            transport=self.execution.execution_pool.model_json_http_client,
            admission=admission,
            cache=self._tokenization_cache(binding),
        ).bind(
            model=binding.model,
            model_stack_digest=binding.model_stack_digest,
            tokenizer_sha256=binding.tokenizer_sha256,
            chat_template_sha256=binding.chat_template_sha256,
        )

    def _qualified_bindings(
        self,
        requirement: NoetriumUnit,
        context: ResearchBindingResolutionContext,
    ):
        program = self.manifests.program_for(context.definition)
        static_bindings = research_model_binding_units(program, requirement)
        if not static_bindings:
            raise RuntimeError("model requirement produced no static binding Units")
        required_models = tuple(
            str(row.parameters["model_id"])
            for row in static_bindings
        )
        prompt_configuration_id = model_role_requirement_prompt(requirement)
        prompt_definition = (
            None
            if prompt_configuration_id is None
            else program.symbol(prompt_configuration_id)
        )
        prompt_config = (
            {}
            if prompt_definition is None
            else dict(prompt_definition.parameters)
        )
        prompt_generation_ids = {
            row.parameters["prompt_generation_id"]
            for row in static_bindings
        }
        if len(prompt_generation_ids) != 1:
            raise ValueError(
                "model binding Units disagree on prompt generation identity"
            )
        prompt_generation_id = next(iter(prompt_generation_ids))

        discovered = []
        root = self.authority_root / "models"
        seen_paths: set[Path] = set()

        def discover_path(path: Path) -> None:
            if path in seen_paths or not path.is_file():
                return
            seen_paths.add(path)
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
                return
            authority = PersistedQualifiedModelEndpointBinding(closure)
            try:
                binding = authority.binding_for(
                    role=model_role_requirement_role(requirement),
                    capability_id=model_role_requirement_capability(requirement),
                    input_schema_id=model_role_requirement_input_schema(requirement),
                    output_schema_id=model_role_requirement_output_schema(requirement),
                    prompt_generation=prompt_generation_id,
                )
            except (KeyError, LookupError, ValueError):
                return
            discovered.append(
                (
                    binding,
                    prompt_definition,
                    prompt_config,
                    authority,
                    str(path),
                )
            )

        # Canonical model-id authorities are direct-addressable. This is the
        # normal path and avoids decoding every qualified closure on every bind.
        for requested_model in required_models:
            discover_path(
                qualified_model_closure_path(
                    self.authority_root, requested_model
                )
            )

        def has_candidate(requested_model: str) -> bool:
            return any(
                requested_model
                in {row[0].model.model_id, row[0].model.logical_name}
                for row in discovered
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
                    requirement_id=f"{model_role_requirement_role(requirement)}:{requested_model}",
                    requirement_digest=requirement.unit_digest,
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
                    f"model panel member {model_role_requirement_role(requirement)!r}/"
                    f"{requested_model!r} resolves multiple scientific "
                    "generations; freeze an exact qualified member"
                )
            chosen = min(candidates, key=lambda row: row[4])
            selected.append(chosen[:4])
        return tuple(selected)

    def _project_model_binding(
        self,
        requirement: NoetriumUnit,
        binding,
        prompt_definition,
        prompt_config,
        authority,
    ) -> ProjectModelBinding:
        generation = model_role_requirement_capability(requirement) in {
            "generation",
            "structured-generation",
        }
        required_capabilities = set(model_role_requirement_capabilities(requirement))
        if generation and bool(prompt_config.get("structured_output", False)):
            required_capabilities.add("structured_output")

        model_requirement = model_capability_requirement_unit(
            role=model_role_requirement_role(requirement),
            prompt_generation_id=(
                None
                if not generation
                else str(
                    prompt_config.get(
                        "prompt_generation_id",
                        model_role_requirement_prompt(requirement),
                    )
                )
            ),
            prompt_id=(
                None
                if not generation
                else str(
                    prompt_config.get(
                        "prompt_id",
                        model_role_requirement_prompt(requirement),
                    )
                )
            ),
            prompt_digest=(
                None
                if not generation
                else prompt_definition.symbol_digest
            ),
            required_capabilities=tuple(sorted(required_capabilities)),
            minimum_context_tokens=model_role_requirement_minimum_context(requirement),
            capability_id=model_role_requirement_capability(requirement),
            input_schema_id=model_role_requirement_input_schema(requirement),
            output_schema_id=model_role_requirement_output_schema(requirement),
        )
        profile = ModelProviderProfile(
            "noetrium.qualified-model",
            tuple(sorted(binding.verified_capabilities)),
        )
        tokenization_digest = None
        if generation:
            tokenization_digest = self._tokenization_for(binding).identity.digest()
        return resolve_qualified_project_binding(
            profile=profile,
            requirement=model_requirement,
            bindings=authority,
            request_tokenization_digest=tokenization_digest,
        )

    def resolve(
        self,
        requirement: NoetriumUnit,
        context: ResearchBindingResolutionContext,
    ):
        """Resolve one immutable Model requirement once per Program/project cut."""

        program = self.manifests.program_for(context.definition)
        cache_key = (
            program.unit_digest,
            requirement.unit_digest,
            context.resolution.project_subject.key,
        )
        with self._binding_resolution_lock:
            cached = self._binding_resolutions.get(cache_key)
        if cached is not None:
            return cached

        bindings = research_model_binding_units(program, requirement)
        owner = CompositionSubject.system_subject(SystemIdentity("model"))
        rows = []
        for binding in bindings:
            params = binding.parameters
            profile_digest = canonical_digest({
                "schema": "noetrium.research-model-binding.v2",
                "model_definition_digest": params["model_definition_digest"],
                "model_id": params["model_id"],
                "prompt_generation_id": params["prompt_generation_id"],
                "prompt_digest": params["prompt_digest"],
                "capabilities": tuple(params["capabilities"]),
            })
            proof = BindingProof(
                owner=owner,
                subject=context.resolution.project_subject,
                requirement_digest=Sha256Digest(requirement.unit_digest),
                provider_identity="noetrium.model",
                provider_profile_digest=Sha256Digest(profile_digest),
                binding_generation="model-" + profile_digest[:24],
            )
            rows.append(BindingResolution.bound(binding, proof))
        resolved = tuple(rows)
        with self._binding_resolution_lock:
            existing = self._binding_resolutions.setdefault(cache_key, resolved)
        if existing != resolved:
            raise RuntimeError(
                "immutable Model requirement resolved to multiple binding closures"
            )
        return existing

    @staticmethod
    def _method_router_semantic_key(execution) -> str:
        """Project one Experiment binding to the exact Model-runtime semantics.

        Experiment, benchmark, Trial, participant and proof-subject identity are
        deliberately excluded: they remain authoritative on the Experiment
        binding but cannot change the Method model router.  This makes runtime
        materialization proportional to the number of distinct model semantic
        configurations rather than the number of experiments.
        """

        execution = require_experiment_execution_binding(execution)
        study = execution.experiment_definition
        frozen_binding = execution.experiment_binding
        requirements = []
        for requirement in binding_requirements_model_roles(
            study_binding_requirements(study)
        ):
            usage = model_role_requirement_usage(requirement)
            capability = model_role_requirement_capability(requirement)
            if (
                not usage.affects_execution
                or capability not in {"generation", "structured-generation"}
            ):
                continue
            role = model_role_requirement_role(requirement)
            members = tuple(
                sorted(
                    frozen_binding.model_role_bindings_for(role),
                    key=lambda row: row.member_index,
                )
            )
            requirements.append({
                "role": role,
                "usage": usage.value,
                "required": model_role_requirement_required(requirement),
                "capability_id": capability,
                "required_capabilities": tuple(
                    model_role_requirement_capabilities(requirement)
                ),
                "input_schema_id": model_role_requirement_input_schema(
                    requirement
                ),
                "output_schema_id": model_role_requirement_output_schema(
                    requirement
                ),
                "minimum_context_tokens": (
                    model_role_requirement_minimum_context(requirement)
                ),
                "prompt_configuration_id": model_role_requirement_prompt(
                    requirement
                ),
                "members": tuple(
                    {
                        "member_index": row.member_index,
                        "model_definition_digest": row.binding.parameters[
                            "model_definition_digest"
                        ],
                        "model_id": row.model_id,
                        "prompt_generation_id": row.prompt_generation_id,
                        "prompt_digest": row.prompt_digest,
                        "capabilities": row.capabilities,
                    }
                    for row in members
                ),
            })
        return canonical_digest({
            "schema": "noetrium.method-model-router-semantics.v1",
            "requirements": tuple(requirements),
        })

    def method_agent_loop_router(
        self,
        execution,
        context: ResearchExecutionContext,
    ) -> MethodAgentLoopRouter | None:
        """Return one shared router per exact Model-runtime semantic cut."""

        execution = require_experiment_execution_binding(execution)
        key = self._method_router_semantic_key(execution)
        entry = self._method_routers.get_or_create(
            key,
            lambda: (
                self._materialize_method_agent_loop_router(
                    execution,
                    context,
                ),
            ),
        )
        return entry[0]

    def _materialize_method_agent_loop_router(
        self,
        execution,
        context: ResearchExecutionContext,
    ) -> MethodAgentLoopRouter | None:
        execution = require_experiment_execution_binding(execution)
        # Materialize every frozen scientific panel member, then expose exactly
        # one role-level loop. Multi-member roles fan out without implicit choice.
        study = execution.experiment_definition
        frozen_binding = execution.experiment_binding
        manifest = self.manifests.resolve(study)
        resolution = resolve_research_requirements(study, manifest)
        resolution_context = ResearchBindingResolutionContext.create(
            study, manifest, resolution
        )
        if resolution.resolution_digest != research_plan_value(execution.research_plan, "requirement_resolution_digest"):
            raise RuntimeError(
                "Study model runtime resolution drifted from frozen execution"
            )

        # Late physical materialization: only Models actually consumed by this
        # execution execution are realized. Static Study/Experiment compilation
        # has already completed entirely from NoetriumUnit semantics.
        required_models = tuple(
            RequiredModelRuntime(
                model_id=frozen_row.model_id,
                role=model_role_requirement_role(requirement),
                required_capabilities=frozen_row.capabilities,
                minimum_context_tokens=model_role_requirement_minimum_context(requirement),
            )
            for requirement in binding_requirements_model_roles(study_binding_requirements(study))
            if (
                model_role_requirement_usage(requirement).affects_execution
                and model_role_requirement_capability(requirement)
                in {"generation", "structured-generation"}
            )
            for frozen_row in tuple(
                sorted(
                    frozen_binding.model_role_bindings_for(model_role_requirement_role(requirement)),
                    key=lambda row: row.member_index,
                )
            )
        )
        if required_models:
            replica_pool = context.model_replica_pool
            if replica_pool is None:
                raise RuntimeError(
                    "late model materialization requires model replica pool"
                )
            runtime_requirement_key = canonical_digest({
                "schema": "noetrium.model-runtime-requirement-set.v1",
                "requirements": tuple(
                    sorted(
                        (
                            row.model_id,
                            row.role,
                            row.required_capabilities,
                            row.minimum_context_tokens,
                        )
                        for row in required_models
                    )
                ),
            })
            def refresh_runtime_requirement_set() -> bool:
                model_phase = (
                    None
                    if context.causal_context is None
                    else CausalPhaseTrace(
                        context.runtime.operation_runtime.forensics,
                        context=context.causal_context,
                        authority_domain="research.execution.model",
                        component_id="research.execution.model",
                        subject="model-consumption:" + runtime_requirement_key,
                        causal_parent_digests=context.causal_event_refs,
                    )
                )
                refresh_required_qualified_model_runtimes(
                    authority_root=self.authority_root,
                    required_models=required_models,
                    assets=context.management.models.assets,
                    resource_authority=(
                        context.management.platform_meta.resource_authority
                    ),
                    model_resources=context.management.models.resources,
                    state_root=(
                        context.management.durable_directories.layout.root(
                            ManagedDirectoryKind.STATE
                        )
                        / "model"
                    ),
                    runtime_workdir=(
                        context.management.physical_directories.layout.root(
                            ManagedDirectoryKind.STATE
                        )
                        / "model"
                        / "runtime-workdir"
                    ),
                    model_replica_pool=replica_pool,
                    deployment_runtime=context.management.models.deployment_runtime,
                    compute_inventory=(
                        context.management.platform_meta.compute_inventory
                    ),
                    gpu_runtime_observer=(
                        context.management.platform_meta.gpu_runtime_observer
                    ),
                    host_runtime_observer=(
                        context.management.platform_meta.host_runtime_observer
                    ),
                    execution_pool=context.execution_pool,
                    phase_trace=model_phase,
                )
                return True

            self._runtime_refreshes.get_or_create(
                runtime_requirement_key,
                refresh_runtime_requirement_set,
            )

        recorder = self._model_request_recorder(context)
        panel_execution = PooledMethodAgentPanelExecution(
            context.execution_pool,
            execution_tenant_id=context.execution_tenant_id,
        )
        loops = {}
        for requirement in binding_requirements_model_roles(study_binding_requirements(study)):
            if (
                not model_role_requirement_usage(requirement).affects_execution
                or model_role_requirement_capability(requirement)
                not in {"generation", "structured-generation"}
            ):
                continue
            frozen_rows = tuple(
                sorted(
                    frozen_binding.model_role_bindings_for(model_role_requirement_role(requirement)),
                    key=lambda row: row.member_index,
                )
            )
            if not frozen_rows:
                if model_role_requirement_required(requirement):
                    raise RuntimeError(
                        f"required execution model role {model_role_requirement_role(requirement)!r} "
                        "has no frozen binding"
                    )
                continue
            if tuple(row.member_index for row in frozen_rows) != tuple(
                range(len(frozen_rows))
            ):
                raise RuntimeError(
                    f"model panel indexes are not contiguous: "
                    f"role={model_role_requirement_role(requirement)!r}"
                )

            qualified = self._qualified_bindings(
                requirement, resolution_context
            )
            if len(qualified) != len(frozen_rows):
                raise RuntimeError(
                    f"model panel cardinality drifted from frozen Study binding: "
                    f"role={model_role_requirement_role(requirement)!r}"
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
                    authority,
                )
                if not projected.qualified:
                    raise RuntimeError(
                        "runtime model binding must be qualified"
                    )
                if frozen_row.model_id not in {
                    projected.model.model_id,
                    projected.model.logical_name,
                }:
                    raise RuntimeError(
                        f"qualified model identity drifted from frozen Unit: "
                        f"role={model_role_requirement_role(requirement)!r} "
                        f"member={frozen_row.member_index}"
                    )
                if (
                    projected.prompt_generation_id
                    != frozen_row.prompt_generation_id
                    or projected.prompt_digest != frozen_row.prompt_digest
                ):
                    raise RuntimeError(
                        f"qualified model prompt identity drifted from frozen Unit: "
                        f"role={model_role_requirement_role(requirement)!r} "
                        f"member={frozen_row.member_index}"
                    )
                if not set(frozen_row.capabilities).issubset(
                    projected.capabilities
                ):
                    raise RuntimeError(
                        f"qualified model capabilities do not satisfy frozen Unit: "
                        f"role={model_role_requirement_role(requirement)!r} "
                        f"member={frozen_row.member_index}"
                    )
                if (
                    projected.capability_id != model_role_requirement_capability(requirement)
                    or projected.input_schema_id != model_role_requirement_input_schema(requirement)
                    or projected.output_schema_id != model_role_requirement_output_schema(requirement)
                ):
                    raise RuntimeError(
                        "qualified model protocol drifted from frozen Unit"
                    )
                if (
                    projected.model.context_length
                    < model_role_requirement_minimum_context(requirement)
                ):
                    raise RuntimeError(
                        "qualified model context is below frozen Unit requirement"
                    )
                replica_set = authority.replica_set_for(
                    role=model_role_requirement_role(requirement),
                    capability_id=model_role_requirement_capability(requirement),
                    input_schema_id=model_role_requirement_input_schema(requirement),
                    output_schema_id=model_role_requirement_output_schema(requirement),
                    prompt_generation=frozen_row.prompt_generation_id,
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
                    projected.model.logical_name,
                    generation_options,
                )
                member_agent_id = (
                    f"{model_role_requirement_role(requirement)}#{frozen_row.member_index}"
                )
                pool = context.execution_pool.model_endpoint_pool(
                    replica_set,
                    observers=(self._model_raw_observer,),
                )
                tokenization = self._tokenization_for(binding)
                member_loop = MethodModelAgentLoop(
                    binding=MethodModelEndpointBinding(
                        agent_id=member_agent_id,
                        role=model_role_requirement_role(requirement),
                        model=projected.model,
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

            if model_role_requirement_role(requirement) in loops:
                raise RuntimeError(
                    f"duplicate model role runtime identity: "
                    f"{model_role_requirement_role(requirement)!r}"
                )
            if len(member_loops) == 1:
                _, member = member_loops[0]
                loops[model_role_requirement_role(requirement)] = MethodModelAgentLoop(
                    binding=MethodModelEndpointBinding(
                        agent_id=model_role_requirement_role(requirement),
                        role=model_role_requirement_role(requirement),
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
                loops[model_role_requirement_role(requirement)] = MethodAgentPanelLoop(
                    model_role_requirement_role(requirement),
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
        execution,
        *,
        machine_id,
        execution_cut_id,
        graph_node_id,
        semantic_digest,
        binding_digest,
        attempt_id,
    ):
        execution = require_experiment_execution_binding(execution)
        del machine_id
        observed_protocol = research_plan_trial_protocol_identity(execution.research_plan).unit_digest
        if observed_protocol != self.protocol_digest:
            raise ValueError(
                "canonical workload reconciliation protocol identity drifted"
            )
        if self.effect_journal is None:
            raise ResearchReconciliationIndeterminate(
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
            raise ResearchReconciliationIndeterminate(
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
        return ResearchNodeReconciliationProof(
            execution_cut_id=execution_cut_id,
            graph_node_id=graph_node_id,
            semantic_digest=semantic_digest,
            binding_digest=binding_digest,
            attempt_id=attempt_id,
            disposition=ResearchGraphReconciliationDisposition.RETRY,
            authority_id="canonical-workload-effect-boundary",
            evidence_digests=(empty_effect_proof, self.identity_digest),
        )

def _exact_program_symbol(program, symbol_id: str, trait_id: str):
    try:
        row = program.symbol(symbol_id)
    except LookupError as exc:
        raise ResearchBindingRequirementMissing(
            stage=trait_id,
            requirement_id=symbol_id,
            requirement_digest=canonical_digest(
                {
                    "symbol_id": symbol_id,
                    "trait_id": trait_id,
                }
            ),
        ) from exc
    if not row.has_trait(trait_id):
        raise ResearchBindingRequirementMissing(
            stage=trait_id,
            requirement_id=symbol_id,
            requirement_digest=canonical_digest(
                {
                    "symbol_id": symbol_id,
                    "trait_id": trait_id,
                }
            ),
        )
    return row


def _materialize_trial_verifier(
    program,
    study,
    context: ResearchExecutionContext,
    symbol_bindings: ResearchSymbolBindingRegistry,
):
    verifier_ids = tuple(sorted({
        str(package["verifier_requirement_id"])
        for task in benchmark_selected_tasks(
            study_benchmark(study),
            study_benchmark_split_id(study),
        )
        if (package := task_package(task)) is not None
        and package.get("verifier_requirement_id") is not None
    }))
    if not verifier_ids:
        return None, None
    if len(verifier_ids) != 1:
        raise ValueError(
            "one Trial verifier authority must be explicit per verifier requirement; "
            f"selected={verifier_ids!r}"
        )
    definition = _exact_program_symbol(
        program,
        verifier_ids[0],
        TRAIT_VERIFIER,
    )
    if definition.implementation is None:
        verifier = symbol_bindings.resolve(
            definition,
            owner_trait_id=TRAIT_VERIFIER,
        ).binding
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
class _AutomaticTrialProviderBlueprint:
    """Immutable admission-time semantic closure for one Trial provider.

    Everything here is already resolved while admission proves the provider
    identity.  First physical use must not rescan the Study, manifest, schedule,
    verifier or participant→Method mapping; it may only bind execution-specific
    runtime state/evidence paths.
    """

    execution: object
    program: NoetriumUnit
    program_scope_id: str
    schedule: NoetriumUnit
    participant_methods: tuple[tuple[NoetriumUnit, NoetriumUnit], ...]
    base_inventory: MethodRuntimePortInventory
    lifetime_releaser: object | None
    resource_demand: ResourceCompetitionDemand | None
    verifier: object | None
    verifier_identity_digest: str | None
    provider_identity_digest: str


class _LazyAutomaticTrialProvider:
    """One TrialProvider whose expensive runtime realization is first-use only.

    Admission owns the immutable semantic identity; physical Method/workload
    runtime construction belongs to the first Trial effect boundary.  The
    realized binding must reproduce the exact admission digest.
    """

    def __init__(
        self,
        *,
        protocol_identity: NoetriumUnit,
        provider_identity_digest: str,
        verifier_identity_digest: str | None,
        resource_demand: ResourceCompetitionDemand | None,
        factory,
    ) -> None:
        if type(protocol_identity) is not NoetriumUnit:
            raise TypeError(
                "lazy Trial provider requires exact protocol identity Unit"
            )
        require_sha256(
            provider_identity_digest,
            "lazy Trial provider semantic identity",
        )
        if verifier_identity_digest is not None:
            require_sha256(
                verifier_identity_digest,
                "lazy Trial provider verifier identity",
            )
        if resource_demand is not None and not isinstance(
            resource_demand, ResourceCompetitionDemand
        ):
            raise TypeError(
                "lazy Trial provider resource_demand must be ResourceCompetitionDemand"
            )
        if not callable(factory):
            raise TypeError("lazy Trial provider factory must be callable")
        self.protocol_identity = protocol_identity
        self.identity_digest = provider_identity_digest
        self._factory = factory
        self._lock = Lock()
        self._binding = None
        self._expected_binding_digest = canonical_digest({
            "provider_identity": _AUTO_WORKLOAD_PROVIDER,
            "provider_identity_digest": provider_identity_digest,
            "verifier_identity_digest": verifier_identity_digest,
            "resource_demand_digest": (
                None
                if resource_demand is None
                else canonical_digest(resource_demand)
            ),
        })

    def _resolved_binding(self) -> ResearchExperimentTrialProviderBinding:
        binding = self._binding
        if binding is not None:
            return binding
        with self._lock:
            binding = self._binding
            if binding is not None:
                return binding
            candidate = self._factory()
            if type(candidate) is not ResearchExperimentTrialProviderBinding:
                raise TypeError(
                    "lazy Trial provider factory returned invalid binding"
                )
            if candidate.binding_digest != self._expected_binding_digest:
                raise RuntimeError(
                    "lazy Trial provider realization drifted from admission identity"
                )
            if candidate.provider.protocol_identity != self.protocol_identity:
                raise RuntimeError(
                    "lazy Trial provider realization protocol identity drifted"
                )
            self._binding = candidate
            return candidate

    def prepare_trial(
        self,
        request: TrialExecutionRequest,
        control: ExecutionControlPort,
    ) -> None:
        provider = self._resolved_binding().provider
        if isinstance(provider, TrialPreparationPort):
            provider.prepare_trial(request, control)

    def run_trial(
        self,
        request: TrialExecutionRequest,
        control: ExecutionControlPort,
    ) -> TrialExecutionReceipt | TrialExecutionStageReceipt:
        return self._resolved_binding().provider.run_trial(request, control)


@dataclass(frozen=True, slots=True)
class PortfolioAutomaticTrialProviderResolver:
    """Build the canonical workload TrialProvider directly from frozen Study IR."""

    manifests: PortfolioDerivedProjectManifestResolver
    context: ResearchExecutionContext
    runtime_inventory: MethodRuntimePortInventory
    model_resolver: PortfolioQualifiedModelResolver
    symbol_bindings: ResearchSymbolBindingRegistry
    lifetime_releaser: object | None = None
    program_journal: DirectoryMachineJournal | None = None
    _method_inventory_lock: object = field(
        default_factory=RLock, init=False, repr=False, compare=False
    )
    _method_inventories: dict[
        tuple[str, str, str], MethodRuntimePortInventory
    ] = field(default_factory=dict, init=False, repr=False, compare=False)

    def _method_inventory_for(
        self,
        program: NoetriumUnit,
        method: NoetriumUnit,
        base: MethodRuntimePortInventory,
        journal: DirectoryMachineJournal,
    ) -> MethodRuntimePortInventory:
        """Reuse one immutable Method activation inventory per semantic cut.

        The expensive symbol/implementation walk is a pure function of the
        immutable Program, selected Method and already-scoped base inventory.
        Execution-specific evidence paths are attached later by
        ``compose_method_runtime_bindings`` and are deliberately not shared.
        """

        key = (program.unit_digest, method.unit_digest, base.identity_digest)
        with self._method_inventory_lock:
            cached = self._method_inventories.get(key)
            if cached is not None:
                return cached
        resolved = compose_research_node_method_runtime_inventory(
            program.symbols,
            base,
            method_graph_digests=(method.unit_digest,),
            journal=journal,
            max_steps=None,
        )
        with self._method_inventory_lock:
            current = self._method_inventories.setdefault(key, resolved)
            if current.identity_digest != resolved.identity_digest:
                raise RuntimeError(
                    "immutable Method inventory produced multiple identities"
                )
            return current

    def _materialize_binding(
        self,
        blueprint: _AutomaticTrialProviderBlueprint,
    ) -> ResearchExperimentTrialProviderBinding:
        """Bind only execution-specific runtime state from a frozen blueprint."""

        if not isinstance(blueprint, _AutomaticTrialProviderBlueprint):
            raise TypeError(
                "automatic Trial provider materialization requires frozen blueprint"
            )
        execution = require_experiment_execution_binding(blueprint.execution)
        program = blueprint.program
        program_scope_id = blueprint.program_scope_id
        program_journal = self.program_journal
        if program_journal is None:
            raise RuntimeError(
                "automatic Trial provider requires canonical program journal authority"
            )

        # Runtime ports are the only part intentionally delayed until first
        # physical use.  The model router itself is globally hash-consed by exact
        # model semantics; all Study/manifest semantics were frozen at admission.
        study_inventory = MethodRuntimePortInventory(
            agent_loop=self.model_resolver.method_agent_loop_router(
                execution,
                self.context,
            ),
            capabilities=blueprint.base_inventory.capabilities,
            unit_activation=blueprint.base_inventory.unit_activation,
            schemas=blueprint.base_inventory.schemas,
        ).for_program_scope(program_scope_id)

        participant_runtimes = []
        method_inventories: dict[str, MethodRuntimePortInventory] = {}
        for requirement, method in blueprint.participant_methods:
            program_inventory = method_inventories.get(method.unit_digest)
            if program_inventory is None:
                program_inventory = self._method_inventory_for(
                    program,
                    method,
                    study_inventory,
                    program_journal,
                )
                method_inventories[method.unit_digest] = program_inventory
            runtime = compose_method_runtime_bindings(
                method,
                program_inventory,
                bind_runtime=bind_standard_method_runtime,
                runtime_binder_digest=METHOD_RUNTIME_BINDER_DIGEST,
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
                    / execution.binding_digest
                    / participant_requirement_role(requirement)
                ),
            )
            participant_runtimes.append(
                ParticipantMethodBinding(
                    participant_requirement_role(requirement),
                    participant_requirement_kind(requirement),
                    participant_requirement_treatment_id(requirement),
                    method,
                    runtime,
                )
            )

        # Acquire the flattened physical-domain set in one global total order.
        # Composite Method/Panel/Router order must never introduce a resource
        # hold-and-wait cycle between concurrent multi-endpoint Trials.
        resource_roots: list[MethodLifetimeResourcePort] = []
        for participant in participant_runtimes:
            agent_loop = participant.runtime.agent_loop
            if isinstance(agent_loop, MethodLifetimeResourcePort):
                resource_roots.append(agent_loop)
            elif callable(getattr(agent_loop, "reserve_lifetime", None)):
                raise TypeError(
                    "Method lifetime resource does not expose Authority claims"
                )
        resolved_method_lifetime_resources = method_lifetime_resources(
            resource_roots
        )

        lifetime_releaser = blueprint.lifetime_releaser
        trial_lifecycle_identity_digest = canonical_digest(
            {
                "schema": "noetrium.trial-lifecycle-release.v5",
                "method_lifetime_resource_digests": tuple(sorted(
                    resource.identity_digest
                    for resource in resolved_method_lifetime_resources
                )),
                "environment_lifetime_release": (
                    None
                    if lifetime_releaser is None
                    else lifetime_releaser.identity_digest
                ),
            }
        )

        def prepare_trial_lifetime(
            request,
            control: ExecutionControlPort,
        ) -> None:
            """Reserve protected model service before physical environment prewarm.

            The Trial clock starts only after both resources are ready.  Model
            capacity is admitted first because it is cheaper than Minecraft
            materialization; environment failure rolls the model reservation
            back immediately.
            """

            reserved_resources: list[MethodLifetimeResourcePort] = []
            try:
                # Admit all Model roles in one Authority transaction. Flattened
                # participants may share one physical Qwen deployment: acquiring
                # pools one by one creates a permanent hold-and-wait cycle.
                reserve_method_lifetime_resources(
                    resolved_method_lifetime_resources,
                    request.assignment_lifetime_id,
                    request.execution_context,
                    control,
                )
                reserved_resources.extend(resolved_method_lifetime_resources)
                if lifetime_releaser is not None:
                    prepare_assignment_environment_trial(
                        lifetime_releaser,
                        request,
                        control,
                    )
            except BaseException as primary:
                cleanup: list[BaseException] = []
                for resource in reversed(reserved_resources):
                    try:
                        resource.release_lifetime(
                            request.assignment_lifetime_id
                        )
                    except BaseException as exc:
                        cleanup.append(exc)
                if cleanup:
                    raise BaseExceptionGroup(
                        "trial preparation and Method lifetime rollback failed",
                        [primary, *cleanup],
                    ) from primary
                raise

        def finalize_trial_lifetime(request) -> None:
            errors: list[BaseException] = []
            for resource in reversed(resolved_method_lifetime_resources):
                try:
                    resource.release_lifetime(
                        request.assignment_lifetime_id
                    )
                except BaseException as exc:
                    errors.append(exc)
            if lifetime_releaser is not None:
                try:
                    release_assignment_environment_trial(
                        lifetime_releaser,
                        request,
                    )
                except BaseException as exc:
                    errors.append(exc)
            if errors:
                raise BaseExceptionGroup(
                    "trial model/environment lifetime release failed",
                    errors,
                )

        task_workload = ScheduledParticipantWorkloadBinding(
            schedule=blueprint.schedule,
            participants=tuple(participant_runtimes),
            journal=program_journal,
            execution_pool=self.context.execution_pool,
            run_finalizer=self.context.runtime.observability.raw.release_run,
            task_finalizer=(
                None
                if lifetime_releaser is None
                else lifetime_releaser.release_context
            ),
            task_finalizer_identity_digest=(
                None
                if lifetime_releaser is None
                else lifetime_releaser.identity_digest
            ),
        )
        workload = bind_workload_graph(
            task_workload,
            journal=program_journal,
        )
        provider = WorkloadTrialProvider(
            protocol_identity=research_plan_trial_protocol_identity(
                execution.research_plan
            ),
            workload=workload,
            measurement_projection=StandardWorkloadMeasurementProjection(),
            execution_budget=self.context.execution_budget,
            artifact_publisher=(
                None
                if blueprint.verifier is None
                else ResearchExecutionVerifierArtifactPublisher(
                    self.context.content
                )
            ),
            trial_preparer=prepare_trial_lifetime,
            trial_finalizer=finalize_trial_lifetime,
            lifecycle_identity_digest=trial_lifecycle_identity_digest,
        )
        return ResearchExperimentTrialProviderBinding(
            _AUTO_WORKLOAD_PROVIDER,
            provider,
            blueprint.provider_identity_digest,
            blueprint.verifier,
            blueprint.verifier_identity_digest,
            resource_demand=blueprint.resource_demand,
        )

    def resolve(self, execution) -> ResearchExperimentTrialProviderBinding:
        """Freeze Trial runtime semantics without eagerly building Method runtimes."""

        execution = require_experiment_execution_binding(execution)
        provider_id = study_plan_provider_id(
            research_plan_study(execution.research_plan)
        )
        if provider_id != _AUTO_WORKLOAD_PROVIDER:
            raise LookupError(
                "Study selected a non-canonical Trial provider; declare its "
                "research semantics in the NoetriumUnit"
            )
        program = self.manifests.program_for(execution.experiment_definition)
        requirements = binding_requirements_participants(
            study_binding_requirements(execution.experiment_definition)
        )
        if not requirements:
            raise RuntimeError(
                "automatic workload Trial execution requires at least one participant"
            )
        schedule = compile_research_participant_schedule(
            execution.experiment_definition,
            execution.experiment_binding,
        )
        if schedule is None:
            raise RuntimeError(
                "participant execution requires the frozen participant schedule"
            )
        exact_methods = self.manifests.method_programs_for(program)
        participant_semantics = []
        participant_methods: list[tuple[NoetriumUnit, NoetriumUnit]] = []
        for requirement in requirements:
            method = exact_methods.get(
                participant_requirement_method_id(requirement)
            )
            if method is None:
                raise LookupError(
                    "Study has no frozen NoetriumUnit for "
                    f"{participant_requirement_method_id(requirement)!r}"
                )
            participant_methods.append((requirement, method))
            participant_semantics.append((
                participant_requirement_role(requirement),
                participant_requirement_kind(requirement),
                participant_requirement_treatment_id(requirement),
                method.unit_digest,
            ))

        program_scope_id = self.manifests.scope_id_for_program(program)
        lifetime_releaser = self.lifetime_releaser
        resource_demand = None
        if lifetime_releaser is not None:
            demand_selector = getattr(
                lifetime_releaser,
                "resource_demand_for_program",
                None,
            )
            if callable(demand_selector):
                resource_demand = demand_selector(program_scope_id)
                if resource_demand is not None and not isinstance(
                    resource_demand, ResourceCompetitionDemand
                ):
                    raise TypeError(
                        "program environment resource demand must be ResourceCompetitionDemand"
                    )
            selector = getattr(lifetime_releaser, "for_program", None)
            if callable(selector):
                lifetime_releaser = selector(program_scope_id)
        verifier, verifier_identity_digest = _materialize_trial_verifier(
            program,
            execution.experiment_definition,
            self.context,
            self.symbol_bindings,
        )
        budget_identity = getattr(
            self.context.execution_budget, "identity_digest", None
        )
        if type(budget_identity) is not str:
            raise TypeError(
                "automatic Trial provider requires execution budget identity"
            )
        require_sha256(
            budget_identity,
            "automatic Trial provider execution budget identity",
        )
        base_inventory = self.runtime_inventory.for_program_scope(
            program_scope_id
        )
        provider_identity_digest = canonical_digest({
            "schema": "noetrium.workload-trial-provider-semantics.v1",
            "execution_binding_digest": execution.binding_digest,
            "protocol_identity": (
                research_plan_trial_protocol_identity(
                    execution.research_plan
                ).unit_digest
            ),
            "program_unit_digest": program.unit_digest,
            "program_scope_id": program_scope_id,
            "participant_schedule_digest": schedule.unit_digest,
            "participants": tuple(participant_semantics),
            "model_router_semantics": (
                self.model_resolver._method_router_semantic_key(execution)
            ),
            "runtime_inventory_digest": base_inventory.identity_digest,
            "execution_budget_identity": budget_identity,
            "lifecycle_identity_digest": (
                None
                if lifetime_releaser is None
                else lifetime_releaser.identity_digest
            ),
            "verifier_identity_digest": verifier_identity_digest,
            "measurement_projection": (
                StandardWorkloadMeasurementProjection().identity_digest
            ),
            "runtime_binder": METHOD_RUNTIME_BINDER_DIGEST,
        })
        blueprint = _AutomaticTrialProviderBlueprint(
            execution=execution,
            program=program,
            program_scope_id=program_scope_id,
            schedule=schedule,
            participant_methods=tuple(participant_methods),
            base_inventory=base_inventory,
            lifetime_releaser=lifetime_releaser,
            resource_demand=resource_demand,
            verifier=verifier,
            verifier_identity_digest=verifier_identity_digest,
            provider_identity_digest=provider_identity_digest,
        )
        lazy_provider = _LazyAutomaticTrialProvider(
            protocol_identity=research_plan_trial_protocol_identity(
                execution.research_plan
            ),
            provider_identity_digest=provider_identity_digest,
            verifier_identity_digest=verifier_identity_digest,
            resource_demand=resource_demand,
            factory=partial(self._materialize_binding, blueprint),
        )
        return ResearchExperimentTrialProviderBinding(
            _AUTO_WORKLOAD_PROVIDER,
            lazy_provider,
            provider_identity_digest,
            verifier,
            verifier_identity_digest,
            resource_demand=resource_demand,
        )


def _model_definition_owner_identity(
    definition: NoetriumUnit,
    bindings: tuple[object, ...],
) -> str:
    """Static MODEL owner identity derived only from NoetriumUnit semantics."""

    if type(definition) is not NoetriumUnit:
        raise TypeError("model definition owner requires NoetriumUnit")
    if type(bindings) is not tuple or not bindings:
        raise TypeError("model definition owner requires non-empty bindings")
    binding_digests = tuple(
        sorted(
            str(getattr(row, "binding_digest"))
            for row in bindings
        )
    )
    return canonical_digest(
        {
            "schema": "noetrium.model-definition-owner.v2",
            "definition_digest": definition.symbol_digest,
            "binding_digests": binding_digests,
        }
    )


def _materialize_platform_symbol_bindings(
    portfolio: NoetriumUnit,
    *,
    context: ResearchExecutionContext,
    manifests: PortfolioDerivedProjectManifestResolver,
    research_bindings: ResearchBindingAuthority,
    environment_runtime,
    pre_materialized_studies: Mapping[str, object] | None = None,
    phase_trace: CausalPhaseTrace | None = None,
) -> tuple[
    ResearchSymbolBindingRegistry,
    dict[
        str,
        tuple[
            NoetriumUnit,
            ResearchBindingContribution,
            NoetriumUnit,
            NoetriumUnit,
        ],
    ],
]:
    rows: dict[tuple[str, str], ResearchSymbolBinding] = {}
    studies: list[tuple[object, object, NoetriumUnit]] = []
    precompiled_experiments: dict[
        str,
        tuple[
            NoetriumUnit,
            ResearchBindingContribution,
            NoetriumUnit,
            NoetriumUnit,
        ],
    ] = {}
    model_symbol_bindings: dict[
        str, tuple[object, dict[str, object]]
    ] = {}
    model_definitions_by_program: dict[str, dict[str, list[object]]] = {}
    participant_definitions_by_program: dict[str, dict[str, list[object]]] = {}
    benchmark_definitions_by_program: dict[str, dict[str, list[object]]] = {}
    cached_studies = (
        {} if pre_materialized_studies is None else dict(pre_materialized_studies)
    )

    def add(
        symbol,
        *,
        owner_trait_id: str,
        owner: str,
        provider: str,
        identity: str,
        binding: object,
    ) -> None:
        candidate = ResearchSymbolBinding(
            symbol.symbol_id,
            owner_trait_id,
            symbol.symbol_digest,
            owner,
            provider,
            identity,
            binding,
        )
        key = (symbol.symbol_digest, owner_trait_id)
        previous = rows.get(key)
        if previous is not None and previous.binding_digest != candidate.binding_digest:
            raise RuntimeError(
                "one platform NoetriumUnit trait resolved to multiple owner bindings: "
                f"{symbol.symbol_id}:{owner_trait_id}"
            )
        rows[key] = candidate

    environment_by_program = (
        {}
        if environment_runtime is None
        else dict(environment_runtime.runtimes)
    )

    for program in portfolio.units_with_schema(TRAIT_PROGRAM):
        program_scope_id = manifests.scope_id_for_program(program)
        model_index: dict[str, list[object]] = {}
        participant_index: dict[str, list[object]] = {}
        benchmark_index: dict[str, list[object]] = {}
        model_definitions_by_program[program_scope_id] = model_index
        participant_definitions_by_program[program_scope_id] = participant_index
        benchmark_definitions_by_program[program_scope_id] = benchmark_index

        # One membership index per live semantic index eliminates the
        # quadratic duplicate scan for repeated role/benchmark symbols.
        # The ordered lists remain canonical for downstream binding order.
        indexed_digests: dict[int, dict[str, set[str]]] = {}

        def index_once(index: dict[str, list[object]], key: object, definition: object) -> None:
            if type(key) is not str or not key:
                return
            seen = indexed_digests.setdefault(id(index), {}).setdefault(key, set())
            digest = definition.symbol_digest
            if digest in seen:
                return
            seen.add(digest)
            index.setdefault(key, []).append(definition)

        for definition in program.symbols:
            if definition.platform_resolved:
                if definition.has_trait(TRAIT_MODEL):
                    index_once(model_index, definition.symbol_id, definition)
                if definition.has_trait(TRAIT_PARTICIPANT):
                    index_once(participant_index, definition.symbol_id, definition)
                    if isinstance(definition.parameters, Mapping):
                        index_once(
                            participant_index,
                            definition.parameters.get("role"),
                            definition,
                        )
                if definition.has_trait(TRAIT_BENCHMARK):
                    index_once(benchmark_index, definition.symbol_id, definition)
                    if isinstance(definition.parameters, Mapping):
                        index_once(
                            benchmark_index,
                            definition.parameters.get("benchmark_id"),
                            definition,
                        )

            if definition.has_trait(TRAIT_PROTOCOL):
                study = cached_studies.get(definition.symbol_digest)
                if study is None:
                    if definition.implementation is not None:
                        study = materialize_research_protocol_definition(
                            definition,
                            declared_measurements=research_measurement_definitions(
                                scoped_protocol_metric_symbols(program, definition)
                            ),
                        )
                    else:
                        study = materialize_platform_research_protocol_binding(
                            definition,
                            declared_measurements=research_measurement_definitions(
                                scoped_protocol_metric_symbols(program, definition)
                            ),
                        )
                    cached_studies[definition.symbol_digest] = study
                if definition.platform_resolved:
                    add(
                        definition,
                        owner_trait_id=TRAIT_PROTOCOL,
                        owner="experimentation",
                        provider="experimentation.study-protocol",
                        identity=study_definition_digest(study),
                        binding=study,
                    )
                studies.append((program, definition, study))
                continue

            if not definition.platform_resolved:
                continue

            if definition.has_trait(TRAIT_CONFIGURATION):
                add(
                    definition,
                    owner_trait_id=TRAIT_CONFIGURATION,
                    owner="research",
                    provider="research.immutable-configuration",
                    identity=definition.symbol_digest,
                    binding=definition.parameters,
                )
                continue

            if definition.has_trait(TRAIT_ENVIRONMENT):
                runtime = environment_by_program.get(program_scope_id)
                if (
                    runtime is not None
                    and runtime.symbol_digest == definition.symbol_digest
                ):
                    add(
                        definition,
                        owner_trait_id=TRAIT_ENVIRONMENT,
                        owner="environment",
                        provider=runtime.implementation_id,
                        identity=canonical_digest(
                            {
                                "definition_digest": runtime.symbol_digest,
                                "implementation_id": runtime.implementation_id,
                                "port": runtime.port.identity_digest,
                                "lifetime": runtime.lifetime.identity_digest,
                            }
                        ),
                        binding=runtime,
                    )
                continue

            if definition.has_trait(TRAIT_DATASET):
                config = thaw_json(definition.parameters)
                if not isinstance(config, Mapping):
                    continue
                dataset_id = config.get("dataset_id", definition.symbol_id)
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
                    owner_trait_id=TRAIT_DATASET,
                    owner="data",
                    provider="platform-meta.dataset-registry",
                    identity=canonical_digest(dataset),
                    binding=dataset,
                )
                continue

    for program, definition, study in studies:
        study_phase = (
            None
            if phase_trace is None
            else phase_trace.start(
                "symbol.binding.resolve-study",
                attributes={
                    "program_unit_id": program.unit_id,
                    "study_definition_digest": study_definition_digest(study),
                },
            )
        )
        try:
            _resolution, contribution = research_bindings.resolve(study)
        except ResearchBindingRequirementMissing:
            if phase_trace is not None and study_phase is not None:
                phase_trace.complete(
                    study_phase,
                    attributes={"resolved": False, "reason": "requirement-missing"},
                )
            continue
        except BaseException as exc:
            if phase_trace is not None and study_phase is not None:
                phase_trace.fail(study_phase, exc)
            raise
        else:
            if phase_trace is not None and study_phase is not None:
                phase_trace.complete(
                    study_phase,
                    attributes={
                        "resolved": True,
                        "model_role_binding_count": len(
                            contribution.model_role_bindings
                        ),
                        "participant_binding_count": len(
                            contribution.participant_bindings
                        ),
                    },
                )

        # Freeze the immutable Experiment scientific closure at the same cut
        # that produced the symbol bindings. prepare() must consume this exact
        # result instead of re-running requirement resolution for every node.
        if contribution.binding_assurance_complete:
            plan = compile_research_plan(study, _resolution, contribution)
            experiment_program = compile_experiment_program(
                research_plan_study(plan)
            )
            precompiled_experiments[definition.symbol_digest] = (
                study,
                contribution,
                plan,
                experiment_program,
            )

        program_scope_id = manifests.scope_id_for_program(program)
        model_index = model_definitions_by_program[program_scope_id]
        participant_index = participant_definitions_by_program[program_scope_id]
        benchmark_index = benchmark_definitions_by_program[program_scope_id]

        for requirement in binding_requirements_model_roles(study_binding_requirements(study)):
            definitions = tuple(model_index.get(model_role_requirement_id(requirement), ()))
            bound = contribution.model_role_bindings_for(model_role_requirement_role(requirement))
            if len(definitions) == 1 and bound:
                definition = definitions[0]
                existing = model_symbol_bindings.get(
                    definition.symbol_digest
                )
                if existing is None:
                    by_binding_digest: dict[str, object] = {}
                    model_symbol_bindings[definition.symbol_digest] = (
                        definition,
                        by_binding_digest,
                    )
                else:
                    existing_definition, by_binding_digest = existing
                    if (
                        existing_definition.symbol_digest
                        != definition.symbol_digest
                    ):
                        raise RuntimeError(
                            "model definition owner aggregation identity drift"
                        )
                for row in bound:
                    by_binding_digest[row.binding_digest] = row

        for participant in contribution.participant_bindings:
            definitions = tuple(participant_index.get(participant.role, ()))
            if len(definitions) == 1:
                add(
                    definitions[0],
                    owner_trait_id=TRAIT_PARTICIPANT,
                    owner="participant",
                    provider=participant.binding.provider_id,
                    identity=participant.binding_digest,
                    binding=participant,
                )

        benchmark_definitions = tuple(
            benchmark_index.get(study_benchmark(study).unit_id, ())
        )
        if len(benchmark_definitions) == 1:
            definition = benchmark_definitions[0]
            add(
                definition,
                owner_trait_id=TRAIT_BENCHMARK,
                owner="experimentation",
                provider="experimentation.benchmark-definition",
                identity=definition.symbol_digest,
                binding=definition,
            )

    for definition_digest in sorted(model_symbol_bindings):
        definition, by_binding_digest = model_symbol_bindings[definition_digest]
        role_bindings = tuple(
            by_binding_digest[key] for key in sorted(by_binding_digest)
        )
        add(
            definition,
            owner_trait_id=TRAIT_MODEL,
            owner="model",
            provider="noetrium.model",
            identity=_model_definition_owner_identity(
                definition,
                role_bindings,
            ),
            binding=role_bindings,
        )

    return (
        ResearchSymbolBindingRegistry(tuple(rows.values())),
        precompiled_experiments,
    )


def _project_owned_programs(
    portfolio: NoetriumUnit,
    manifests: tuple[NoetriumUnit, ...],
) -> tuple[tuple[str, tuple[str, ...], NoetriumUnit], ...]:
    """Project-scope program ownership projected from recursive graph containment."""

    rows: list[tuple[str, tuple[str, ...], NoetriumUnit]] = []
    portfolio_roots = portfolio.paths_with_schema(TRAIT_PORTFOLIO)
    single_source_project_id = (
        project_manifest_project_id(manifests[0]) if len(manifests) == 1 else None
    )
    for manifest in manifests:
        project_id = project_manifest_project_id(manifest)
        roots = tuple(
            (path, graph)
            for path, graph in portfolio_roots
            if graph.unit_id == project_id
        )
        if not roots and project_id == single_source_project_id:
            roots = (((portfolio.unit_id,), portfolio),)
        if len(roots) != 1:
            raise LookupError(
                "project manifest does not resolve to exactly one recursive "
                f"portfolio root: project_id={project_id!r} matches={len(roots)}"
            )
        root_path, root = roots[0]
        stack = [
            (child, root_path + (child.unit_id,))
            for child in reversed(root.members)
        ]
        while stack:
            graph, path = stack.pop()
            if graph.has_trait(TRAIT_PORTFOLIO):
                continue
            if graph.has_trait(TRAIT_PROGRAM):
                rows.append((project_id, path, graph))
            stack.extend(
                (child, path + (child.unit_id,))
                for child in reversed(graph.members)
            )
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class LocalResearchExecutionAuthorityMaterializer:
    """Canonical local materializer for every NoetriumUnit cardinality.

    This class owns composition only. Model, Environment, Capability and Trial
    facts stay with their owner systems; later resolver components plug into this
    one root rather than creating project-specific execution paths.
    """

    context: ResearchExecutionContext
    project_manifests: tuple[NoetriumUnit, ...]

    def __post_init__(self) -> None:
        if type(self.context) is not ResearchExecutionContext:
            raise TypeError("local research authority materializer requires ResearchExecutionContext")
        if type(self.project_manifests) is not tuple or not self.project_manifests:
            raise TypeError(
                "local research authority materializer requires non-empty "
                "ProjectManifest Unit tuple"
            )
        for row in self.project_manifests:
            require_project_manifest(row)
        project_ids = tuple(
            project_manifest_project_id(row) for row in self.project_manifests
        )
        if len(project_ids) != len(set(project_ids)):
            raise ValueError(
                "local research authority project identities must be unique"
            )

    def materialize(self, portfolio: NoetriumUnit) -> ResearchExecutionAuthorities:
        require_research_root(portfolio)

        phase_trace = (
            None
            if self.context.causal_context is None
            else CausalPhaseTrace(
                self.context.runtime.operation_runtime.forensics,
                context=self.context.causal_context,
                authority_domain="research.execution.authority",
                component_id="research.execution.authority",
                subject="research-execution:" + portfolio.unit_id,
                causal_parent_digests=self.context.causal_event_refs,
            )
        )

        owned_programs = _project_owned_programs(
            portfolio,
            self.project_manifests,
        )
        manifests = PortfolioDerivedProjectManifestResolver(
            self.project_manifests,
            owned_programs,
        )
        protocol_studies: dict[str, object] = {}
        study_spec_compiler = StudySpecCompiler()
        for program in portfolio.units_with_schema(TRAIT_PROGRAM):
            for definition in program.symbols:
                if not definition.has_trait(TRAIT_PROTOCOL):
                    continue
                if definition.implementation is not None:
                    study = materialize_research_protocol_definition(
                        definition,
                        declared_measurements=research_measurement_definitions(
                            scoped_protocol_metric_symbols(program, definition)
                        ),
                        compiler=study_spec_compiler,
                    )
                else:
                    try:
                        study = materialize_platform_research_protocol_binding(
                            definition,
                            declared_measurements=research_measurement_definitions(
                                scoped_protocol_metric_symbols(program, definition)
                            ),
                            compiler=study_spec_compiler,
                        )
                    except (KeyError, TypeError, ValueError) as exc:
                        raise RuntimeError(
                            "platform-resolved PROTOCOL declarative study failed "
                            "execution-authority bootstrap: "
                            f"{definition.symbol_id}"
                        ) from exc
                # Bootstrap freezes only Unit-derived scientific semantics.
                # Expensive physical model realization is intentionally deferred
                # until the first Unit that actually consumes that Model role.
                protocol_studies[definition.symbol_digest] = study
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

        lifetime_controller = ResourceLifetimeController(
            (
                "research-execution:"
                + portfolio.unit_id
                + ":"
                + portfolio.unit_digest[:24]
            ),
            self.context.execution_pool.owner_generation_id,
            self.context.management.platform_meta.resource_authority,
        )

        environment_phase = (
            None
            if phase_trace is None
            else phase_trace.start("environment.runtime.materialize")
        )
        try:
            environment_runtime = compose_local_environment_capability_runtime(
                portfolio,
                self.context,
            )
        except BaseException as exc:
            if phase_trace is not None and environment_phase is not None:
                phase_trace.fail(environment_phase, exc)
            raise
        else:
            if phase_trace is not None and environment_phase is not None:
                phase_trace.complete(
                    environment_phase,
                    attributes={"present": environment_runtime is not None},
                )
        lifetime_resources = ()
        if environment_runtime is not None:
            environment_owner = lifetime_controller.register(
                "research-environment:" + portfolio.unit_digest[:24],
                retire=environment_runtime.close,
            )
            lifetime_resources = (environment_owner,)
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
            schemas=compile_method_schema_authority(portfolio),
        )
        symbol_phase = (
            None
            if phase_trace is None
            else phase_trace.start("symbol.bindings.materialize")
        )
        try:
            symbol_bindings, precompiled_experiments = _materialize_platform_symbol_bindings(
                portfolio,
                context=self.context,
                manifests=manifests,
                research_bindings=research_bindings,
                environment_runtime=environment_runtime,
                pre_materialized_studies=protocol_studies,
                phase_trace=phase_trace,
            )
        except BaseException as exc:
            if phase_trace is not None and symbol_phase is not None:
                phase_trace.fail(symbol_phase, exc)
            raise
        else:
            if phase_trace is not None and symbol_phase is not None:
                phase_trace.complete(
                    symbol_phase,
                    attributes={"identity_digest": symbol_bindings.identity_digest},
                )
        program_journal = DirectoryMachineJournal(
            self.context.state_root / "machine-state" / "unit-journal"
        )
        trial_phase = (
            None
            if phase_trace is None
            else phase_trace.start("trial.providers.materialize")
        )
        try:
            trial_providers = PortfolioAutomaticTrialProviderResolver(
                manifests,
                self.context,
                runtime_inventory,
                model_resolver,
                symbol_bindings,
                None if environment_runtime is None else environment_runtime.lifetime,
                program_journal,
            )
        except BaseException as exc:
            if phase_trace is not None and trial_phase is not None:
                phase_trace.fail(trial_phase, exc)
            raise
        else:
            if phase_trace is not None and trial_phase is not None:
                phase_trace.complete(trial_phase)
        reconciliation_registrations = []
        seen_protocols = set()
        for program in portfolio.units_with_schema(TRAIT_PROGRAM):
            for definition in program.symbols:
                if definition.has_trait(TRAIT_PROTOCOL):
                    study = protocol_studies.get(definition.symbol_digest)
                    if study is None:
                        raise RuntimeError(
                            "execution-authority reconciliation lost the frozen "
                            f"Study for protocol {definition.symbol_id!r}"
                        )
                    protocol_digest = study_trial_protocol(study).unit_digest
                    if protocol_digest in seen_protocols:
                        continue
                    seen_protocols.add(protocol_digest)
                    reconciliation_registrations.append(
                        ResearchExperimentReconciliationRegistration(
                            _AUTO_WORKLOAD_PROVIDER,
                            protocol_digest,
                            CanonicalWorkloadExperimentReconciliation(
                                protocol_digest,
                                environment_effect_journals.get(manifests.scope_id_for_program(program)),
                            ),
                        )
                    )
        runtime_binding_authority = ResearchExperimentRuntimeBindingAuthority(
            study_execution=ResearchExperimentTrialStudyExecutionResolver(
                trial_providers,
                observation=RawLakeStudyTrialObservationSink(
                    self.context.runtime.observability.raw
                ),
                receipt_publisher=ResearchExecutionTrialReceiptPublisher(
                    self.context.content
                ),
                degradation_sink=ForensicDiagnosticDegradationSink(
                    self.context.runtime.operation_runtime.forensics
                ),
            ),
            reconciliation=ResearchExperimentReconciliationRegistry(
                tuple(reconciliation_registrations)
            ),
        )
        authority_manifest_digest = canonical_digest(
            {
                "schema": "noetrium.local-research-execution-authorities.v1",
                "portfolio_digest": portfolio.unit_digest,
                "project_manifest_digests": tuple(
                    sorted(
                        (
                            project_manifest_project_id(row),
                            project_manifest_digest(row),
                        )
                        for row in self.project_manifests
                    )
                ),
                "symbol_bindings": symbol_bindings.identity_digest,
            }
        )
        return ResearchExecutionAuthorities.from_study_bindings(
            authority_manifest_digest,
            lifetime_controller=lifetime_controller,
            research_bindings=research_bindings,
            experiment_runtime_binding=runtime_binding_authority,
            method_runtime_inventory=runtime_inventory,
            symbol_bindings=symbol_bindings,
            pre_materialized_studies=protocol_studies,
            precompiled_experiments=precompiled_experiments,
            lifetime_resources=lifetime_resources,
        )


def build_local_research_execution_authority_materializer(
    context: ResearchExecutionContext,
    project_manifests: tuple[NoetriumUnit, ...],
) -> ResearchExecutionAuthorityMaterializerPort:
    materializer = LocalResearchExecutionAuthorityMaterializer(
        context,
        project_manifests,
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

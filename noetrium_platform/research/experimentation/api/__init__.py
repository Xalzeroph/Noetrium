from noetrium_platform.research.execution.api import (
    PARTICIPANT_IMPLEMENTATION_TRAIT,
    require_participant_implementation,
    participant_implementation_id,
    participant_implementation_schema,
    participant_implementation_version,
)
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.kernel import MachineCut
from .catalog import ExperimentationCatalogPort
from noetrium_platform.research.experimentation.identity import ModelRoleUsage, ReplayLevel
from noetrium_platform.research.experimentation.binding import (
    ResearchBindingAssuranceGap,
    ResearchBindingContribution,
    ResearchCapabilityBinding,
    ResearchModelRoleBinding,
    ResearchParticipantBinding,
    ResearchRequirementResolution,
    binding_requirements,
    binding_requirements_model_role,
    binding_requirements_model_roles,
    binding_requirements_participants,
    binding_requirements_topology,
    binding_requirements_trial_provider,
    model_role_requirement,
    model_role_requirement_capabilities,
    model_role_requirement_capability,
    model_role_requirement_id,
    model_role_requirement_input_schema,
    model_role_requirement_max_bindings,
    model_role_requirement_minimum_context,
    model_role_requirement_output_schema,
    model_role_requirement_prompt,
    model_role_requirement_required,
    model_role_requirement_role,
    model_role_requirement_usage,
    participant_requirement,
    participant_requirement_capabilities,
    participant_requirement_configurations,
    participant_requirement_kind,
    participant_requirement_method_id,
    participant_requirement_role,
    participant_requirement_treatment_id,
    require_binding_requirements,
    require_model_role_requirement,
    require_participant_requirement,
)
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    materialize_research_study_spec,
    ANALYSIS_DEFINITION_TRAIT,
    MEASUREMENT_CUT_TRAIT,
    AnalysisResult,
    analysis_definition_unit,
    analysis_definition_digest,
    analysis_input_cut,
    analysis_output_schema_id,
    measurement_cut_digest,
    measurement_cut_unit,
    require_analysis_definition,
    require_measurement_cut,
    assignment_workload,
    assignment_workload_digest,
    assignment_workload_task_ids,
    assignment_workload_dependencies_for,
    assignment_workload_prerequisites_for,
    assignment_workload_retry_sources_for,
    validate_assignment_workload,
    benchmark_cut_requirements,
    requires_benchmark_cut,
    BenchmarkSourceKind,
    BenchmarkSourcePort,
    BenchmarkSourceResolution,
    InMemoryBenchmarkSource,
    MeasurementContentReference,
    PostHocEvaluationResult,
    MeasurementRecord,
    MeasurementValue,
    MeasurementValueKind,
    TaskVerifierIsolation,
    task_graph,
    task_graph_relation,
    validate_task_graph,
    TaskRelation,
    TaskVerifierArtifact,
    TaskVerifierPort,
    TaskVerifierReceipt,
    TaskVerifierRequest,
    TrialExecutionReceipt,
    TrialExecutionRequest,
    TrialExecutionStageReceipt,
    TrialProviderPort,
    study_variant_graph,
    VariantKind,
    VariantBinding,
)
from .research_compiler import (
    RESEARCH_PLAN_TRAIT, research_plan_graph, require_research_plan, research_plan_value, research_plan_protocol, research_plan_study, research_plan_digest, research_plan_binding_complete, research_plan_study_identity, research_plan_trial_protocol_identity, ResearchManifestRequirementKeys,
    ResearchManifestRequirementsUnresolved, RESEARCH_PLAN_DIFF_TRAIT, research_plan_diff_value,
    compile_research_plan, diff_research_plans,
    research_manifest_requirement_keys, resolve_research_requirements,
)
from .method_host import compile_research_method
from .sharding import (
    ExperimentBatchPlacement,
    ExperimentShard,
    EXPERIMENT_SHARD_PLAN_TRAIT, experiment_shard_plan_graph, experiment_shards, experiment_batch_placements, experiment_shard_plan_digest, experiment_worker_scope_for_assignment, assert_experiment_shard_complete,
    compile_experiment_shard_plan,
)
from .program import (
    ExperimentBatch,
    ExperimentProgramBinding,
    compile_experiment_program,
    experiment_report_from_data,
)
__all__ = [
    "binding_requirements",
    "binding_requirements_model_role",
    "binding_requirements_model_roles",
    "binding_requirements_participants",
    "binding_requirements_topology",
    "binding_requirements_trial_provider",
    "model_role_requirement",
    "model_role_requirement_capabilities",
    "model_role_requirement_capability",
    "model_role_requirement_id",
    "model_role_requirement_input_schema",
    "model_role_requirement_max_bindings",
    "model_role_requirement_minimum_context",
    "model_role_requirement_output_schema",
    "model_role_requirement_prompt",
    "model_role_requirement_required",
    "model_role_requirement_role",
    "model_role_requirement_usage",
    "participant_requirement",
    "participant_requirement_capabilities",
    "participant_requirement_configurations",
    "participant_requirement_kind",
    "participant_requirement_method_id",
    "participant_requirement_role",
    "participant_requirement_treatment_id",
    "require_binding_requirements",
    "require_model_role_requirement",
    "require_participant_requirement",
    "MachineCut",
    "ResearchBindingAssuranceGap",
    "ResearchBindingContribution",
    "ResearchCapabilityBinding",
    "ResearchModelRoleBinding",
    "ResearchParticipantBinding",
    "ResearchRequirementResolution",
    "ResearchManifestRequirementKeys",
    "ResearchManifestRequirementsUnresolved",
    "research_manifest_requirement_keys",
    "resolve_research_requirements",
    "TaskVerifierArtifact",
    "TaskVerifierPort",
    "TaskVerifierReceipt",
    "TaskVerifierRequest",
    "TrialProviderPort",
    "TrialExecutionRequest",
    "TrialExecutionReceipt",
    "TrialExecutionStageReceipt",
    "ModelRoleUsage",
    "ReplayLevel",
    "AnalysisResult",
    "require_measurement_cut",
    "require_analysis_definition",
    "measurement_cut_unit",
    "measurement_cut_digest",
    "analysis_output_schema_id",
    "analysis_input_cut",
    "analysis_definition_digest",
    "analysis_definition_unit",
    "MEASUREMENT_CUT_TRAIT",
    "ANALYSIS_DEFINITION_TRAIT",
    "PostHocEvaluationResult",
    "assignment_workload", "assignment_workload_digest", "assignment_workload_task_ids", "assignment_workload_dependencies_for", "assignment_workload_prerequisites_for", "assignment_workload_retry_sources_for", "validate_assignment_workload",
    "benchmark_cut_requirements",
    "requires_benchmark_cut",
    "benchmark_cut_requirements",
    "requires_benchmark_cut",
    "BenchmarkSourceKind",
    "BenchmarkSourcePort",
    "BenchmarkSourceResolution",
    "InMemoryBenchmarkSource",
    "MeasurementContentReference",
    "TaskVerifierIsolation",
    "task_graph",
    "task_graph_relation",
    "TaskRelation",
    "research_plan_study_identity",
    "research_plan_trial_protocol_identity",
    "diff_research_plans",
    "compile_research_plan",
    "RESEARCH_PLAN_DIFF_TRAIT",
    "research_plan_diff_value",
    "compile_research_method",
    "ExperimentBatchPlacement",
    "ExperimentShard",
    "compile_experiment_shard_plan",
    "ExperimentBatch",
    "ExperimentProgramBinding",
    "compile_experiment_program",
    "experiment_report_from_data",
    "MeasurementValueKind",
    "MeasurementValue",
    "MeasurementRecord",
]

from noetrium_platform.research.execution.api import (
    ActionKind,
    AgentGoal,
    EmbodiedActionCommand,
    EmbodimentKind,
    GuardDecision,
    GuardVerdict,
    NoetriumUnit,
    method_flow_relation,
    method_operation,
    method_program,
    unit_flow,
    unit_operation,
    executable_unit,
    SensorModality,
)

_EXPERIMENTATION_EXECUTION_AUTHORING_EXPORTS = (
    "ActionKind",
    "AgentGoal",
    "EmbodiedActionCommand",
    "EmbodimentKind",
    "GuardDecision",
    "GuardVerdict",
    "NoetriumUnit",
    "unit_flow", "unit_operation", "executable_unit",
    "SensorModality",
)
__all__ += _EXPERIMENTATION_EXECUTION_AUTHORING_EXPORTS

from noetrium_platform.research.experimentation.workbench.api import (
    TableExpression,
    TableExpressionKind,
)
_EXPERIMENTATION_TABLE_AUTHORING_EXPORTS = (
    "TableExpression",
    "TableExpressionKind",
)
__all__ += _EXPERIMENTATION_TABLE_AUTHORING_EXPORTS
# Canonical static layer ABI.
from noetrium_platform.research.execution.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    EnvironmentCapability,
    EnvironmentProviderPort,
    ExecutionContext,
    JsonValue,
    MethodRuntimeIdentity,
)
from noetrium_platform.research.experimentation.workbench.api import (
    AggregationFunction,
    DataColumn,
    DataTable,
    EvaluationContext,
    EvaluationStage,
    FigureKind,
    FigureOutputFormat,
    MissingValuePolicy,
    MultipleComparisonMethod,
    SplitStrategy,
    StudyObservationTableAdapter,
)

__all__ = [
    'ExperimentationCatalogPort',
    'MachineCut',
    'ResearchBindingContribution',
    'ResearchCapabilityBinding',
    'ResearchModelRoleBinding',
    'ResearchParticipantBinding',
    'ResearchRequirementResolution',
    'resolve_research_requirements',
    'TaskVerifierArtifact',
    'TaskVerifierPort',
    'TaskVerifierReceipt',
    'TaskVerifierRequest',
    'TrialProviderPort',
    'TrialExecutionRequest',
    'TrialExecutionReceipt',
    'TrialExecutionStageReceipt',
    'ModelRoleUsage',
    'ReplayLevel',
    'AnalysisResult',
    'PostHocEvaluationResult',
    'assignment_workload', 'assignment_workload_digest', 'assignment_workload_task_ids', 'assignment_workload_dependencies_for', 'assignment_workload_prerequisites_for', 'assignment_workload_retry_sources_for', 'validate_assignment_workload',
    'benchmark_cut_requirements',
    'requires_benchmark_cut',
    'benchmark_cut_requirements',
    'requires_benchmark_cut',
    'BenchmarkSourceKind',
    'BenchmarkSourcePort',
    'BenchmarkSourceResolution',
    'InMemoryBenchmarkSource',
    'MeasurementContentReference',
    'TaskVerifierIsolation',
    'task_graph',
    'task_graph_relation',
    'TaskRelation',
    'diff_research_plans',
    'compile_research_plan',
    'compile_research_method',
    'ExperimentBatchPlacement',
    'ExperimentShard',
    'compile_experiment_shard_plan',
    'ExperimentBatch',
    'ExperimentProgramBinding',
    'compile_experiment_program',
    'experiment_report_from_data',
    'MeasurementValueKind',
    'MeasurementValue',
    'MeasurementRecord',
    'ActionKind',
    'AgentGoal',
    'EmbodiedActionCommand',
    'EmbodimentKind',
    'GuardDecision',
    'GuardVerdict',
    'NoetriumUnit',
    'SensorModality',
    'TableExpression',
    'TableExpressionKind',
    'CapabilityDescriptor',
    'CapabilityRequest',
    'EnvironmentCapability',
    'EnvironmentProviderPort',
    'ExecutionContext',
    'JsonValue',
    'MethodRuntimeIdentity',
    'AggregationFunction',
    'DataColumn',
    'DataTable',
    'EvaluationContext',
    'EvaluationStage',
    'FigureKind',
    'FigureOutputFormat',
    'MissingValuePolicy',
    'MultipleComparisonMethod',
    'SplitStrategy',
    'StudyObservationTableAdapter',
]


__all__ = tuple(__all__) + ("study_variant_graph",)

__all__ = tuple(__all__) + ("VariantKind",)


__all__ = tuple(__all__) + (
    "NoetriumUnit",
    "VariantBinding",
    "NoetriumUnit",
)


# Adjacent-layer authoring surface consumed by the Product Research execution.
from noetrium_platform.research.execution.api import ActionRequest, ActionResult, CapabilityPort, CapabilityResult, CapabilitySelectionReference, CapabilitySelectionView, EmbodiedCaptureReceipt, EmbodiedEventProjection, EmbodiedEventProjectionKind, EnvironmentConcern, EnvironmentSession, EvaluationConcern, ExperimentConcern, NoetriumUnit, MemoryConcern, MethodAgentRequest, MethodAgentResult, MethodEvent, MethodExecutionClass, MethodNodeKind, MethodNodeRequest, MethodNodeResult, MethodRunResult, MethodRunStatus, MethodRuntimeContext, MethodRuntimePort, OptimizationConcern, ParticipantConcern, NoetriumUnit, program_rule, program_rule_set, UnitOperationBinding, unit_operation_name, executable_unit_nodes, validate_executable_unit, RunConcern, RuntimeConcern, environment_action_capability_payload, environment_branch_action_spec, environment_fork_action_payload, environment_query_capability_payload, environment_replay_action_payload, environment_reset_capability_payload, materialize_capability_selection_view, program_execution_capability_payload

_EXPERIMENTATION_PRODUCT_AUTHORING_EXPORTS = (
    "ActionRequest",
    "ActionResult",
    "CapabilityPort",
    "CapabilityResult",
    "CapabilitySelectionReference",
    "CapabilitySelectionView",
    "EmbodiedCaptureReceipt",
    "EmbodiedEventProjection",
    "EmbodiedEventProjectionKind",
    "EnvironmentConcern",
    "EnvironmentSession",
    "EvaluationConcern",
    "ExperimentConcern",
    "NoetriumUnit",
    "MemoryConcern",
    "MethodAgentRequest",
    "MethodAgentResult",
    "MethodEvent",
    "MethodExecutionClass",
    "MethodNodeKind",
    "MethodNodeRequest",
    "MethodNodeResult",
    "method_flow_relation", "method_operation", "method_program",
    "MethodRunResult",
    "MethodRunStatus",
    "MethodRuntimeContext",
    "MethodRuntimePort",
    "OptimizationConcern",
    "ParticipantConcern",
    "NoetriumUnit",
    "program_rule",
    "program_rule_set",
    "UnitOperationBinding",
    "unit_operation_name",
    "executable_unit_nodes",
    "validate_executable_unit",
    "RunConcern",
    "RuntimeConcern",
    "materialize_capability_selection_view",
    "program_execution_capability_payload",
)
__all__ = tuple(__all__) + _EXPERIMENTATION_PRODUCT_AUTHORING_EXPORTS

# Adjacent-layer branch/replay authoring semantics.
from noetrium_platform.research.execution.api import (
    EnvironmentForkReceipt,
    EnvironmentReplayError,
    EnvironmentReplayReceipt,
    EnvironmentSessionOpener,
    ExecutionForkReceipt,
    ExecutionSourceCut,
    ExecutionStateAnchor,
    bind_execution_fork,
    fork_environment_session,
    replay_environment_prefix,
)
__all__ = tuple(__all__) + (
    "EnvironmentForkReceipt",
    "EnvironmentReplayError",
    "EnvironmentReplayReceipt",
    "EnvironmentSessionOpener",
    "fork_environment_session",
    "replay_environment_prefix",
    "ExecutionForkReceipt",
    "ExecutionSourceCut",
    "ExecutionStateAnchor",
    "bind_execution_fork",
)
from noetrium_platform.research.execution.api import (
    TensorContentRef,
    TensorContentStorePort,
)
__all__ = tuple(__all__) + (
    "TensorContentRef",
    "TensorContentStorePort",
)

# Adjacent execution-layer contracts surfaced to the Product Research execution.
from noetrium_platform.research.execution.api import (
    ArtifactBlobRef,
    EmbodiedSimulatorBackendPort,
    SemanticProjectionSnapshot,
    SemanticSimilarityQuery,
    SemanticSimilarityQueryPort,
    SimulatorObservation,
    SimulatorStep,
    SoftwareActionKind,
    SoftwareActionTimeoutError,
    SoftwareWorldPort,
)
__all__ = tuple(__all__) + (
    "ArtifactBlobRef",
    "EmbodiedSimulatorBackendPort",
    "SemanticProjectionSnapshot",
    "SemanticSimilarityQuery",
    "SemanticSimilarityQueryPort",
    "SimulatorObservation",
    "SimulatorStep",
    "SoftwareActionKind",
    "SoftwareActionTimeoutError",
    "SoftwareWorldPort",
)
from noetrium_platform.research.experimentation.workbench.api import (
    candidate_program_capability_payload,
)
__all__ = tuple(__all__) + ("candidate_program_capability_payload",)

# Adjacent Execution-layer Method runtime views.
from noetrium_platform.research.execution.api import (
    research_component_operations,
    research_method_components,
    validate_research_component,
)

__all__ = tuple(__all__) + (
    "research_component_operations",
    "research_method_components",
    "validate_research_component",
)

__all__ = tuple(__all__) + ("materialize_research_study_spec",)


__all__ = tuple(__all__) + ('analysis_definition_digest',)

__all__ = tuple(__all__) + ('analysis_output_schema_id',)

__all__ = tuple(__all__) + ('require_analysis_definition',)

from noetrium_platform.research.execution.api import (
    method_program_artifact_kinds,
    method_program_configuration,
    method_program_entrypoint,
    method_program_evidence_obligations,
    method_program_execution_class,
    method_program_identity,
    method_program_metric_names,
    method_program_input_schema,
    method_program_output_schema,
    method_program_state_schema,
    validate_method_program,
)
_METHOD_STATIC_VIEW_EXPORTS = (
    "method_program_artifact_kinds",
    "method_program_configuration",
    "method_program_entrypoint",
    "method_program_evidence_obligations",
    "method_program_execution_class",
    "method_program_identity",
    "method_program_metric_names",
    "method_program_input_schema",
    "method_program_output_schema",
    "method_program_state_schema",
    "validate_method_program",
)
__all__ = tuple(__all__) + _METHOD_STATIC_VIEW_EXPORTS

__all__ = tuple(__all__) + ('participant_implementation_id',)

__all__ = tuple(__all__) + ('participant_implementation_schema',)

__all__ = tuple(__all__) + ('participant_implementation_version',)

__all__ = tuple(__all__) + ("PARTICIPANT_IMPLEMENTATION_TRAIT", "require_participant_implementation")

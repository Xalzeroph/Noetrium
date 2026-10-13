from __future__ import annotations

import ast
from pathlib import Path

from ..api import GateFinding, GatePort, GateReport, GateRequest, GateSeverity


_RETIRED_STATIC_CARRIERS = frozenset({
    "AgentIdentity",
    "AgentMethodSpec",
    "AgentPhaseSpec",
    "AgentProjectDefinition",
    "AgentStudySpec",
    "AnalysisDefinition",
    "BaselineSpec",
    "BenchmarkTaskSet",
    "CapabilityProgramBuilder",
    "CommunicationRuntimeSpec",
    "ContextBlockSpec",
    "ExperimentModelRoleSpec",
    "ExperimentParticipantSpec",
    "ExperimentSpec",
    "ExperimentTaskSpec",
    "ExperimentTrialProtocolIdentity",
    "FactorLevelSpec",
    "FactorSelection",
    "FigureSpec",
    "MachineProgramBuilder",
    "MeasurementDefinition",
    "MeasurementProtocol",
    "MemoryPresetSpec",
    "MethodGraphBuilder",
    "MethodIdentity",
    "MethodProgramIdentity",
    "MethodProjectDefinition",
    "MethodWorkflow",
    "ModelCapabilityRequirement",
    "ModelProjectDefinition",
    "ModelRequirementContribution",
    "MultimodalMethodSpec",
    "OptimizationPresetSpec",
    "OutputSchemaSpec",
    "ParticipantImplementationIdentity",
    "ParticipantMessageSchedule",
    "ParticipantRequirement",
    "ParticipantSchedule",
    "ParticipantTopology",
    "ParticipantTopologyMember",
    "PostHocEvaluationDefinition",
    "ProgramSpec",
    "ProjectManifest",
    "ProjectSpec",
    "PromptSection",
    "PromptSpec",
    "ResearchMethodBuilder",
    "ResearchMethodFlowDSL",
    "ResearchPortfolio",
    "ResearchPortfolioBuilder",
    "ResearchStudyDefinition",
    "RuntimeModuleBuilder",
    "RuntimeProgramComposer",
    "Study",
    "StudyExecutionPolicy",
    "StudyFactorSpec",
    "StudyIntervention",
    "StudyModel",
    "StudyParticipant",
    "StudySpec",
    "SynchronizationThresholdSpec",
    "TaskArtifactSpec",
    "TaskDefinition",
    "TaskPackageSpec",
    "TaskSetSplit",
    "TrialTaskProjectionPort",
    "WorkspaceSpec",
})

_STATIC_ROOTS = (
    "noetrium_platform/product",
    "noetrium_platform/research",
    "noetrium_platform/foundation/portfolio",
    "noetrium_platform/capabilities/participant",
    "noetrium_platform/capabilities/model",
)

_FORBIDDEN_SUFFIXES = (
    "Builder",
    "Definition",
    "DSL",
    "Preset",
    "Spec",
    "Topology",
)

_DYNAMIC_NAME_TOKENS = (
    "Authority",
    "Binding",
    "Control",
    "Event",
    "Factory",
    "Identity",
    "Observation",
    "Port",
    "Provider",
    "Receipt",
    "Record",
    "Registry",
    "Request",
    "Resolver",
    "Result",
    "Revision",
    "Runtime",
    "Snapshot",
    "State",
    "Status",
    "Transition",
)


class StaticUnitSemanticsGate(GatePort):
    """Fail if declarative/scientific truth grows a second Python carrier."""

    gate_id = "governance.static-unit-semantics"

    def evaluate(self, request: GateRequest) -> GateReport:
        root = Path(request.root)
        findings: list[GateFinding] = []
        for relative_root in _STATIC_ROOTS:
            source_root = root / relative_root
            if not source_root.exists():
                continue
            for path in source_root.rglob("*.py"):
                try:
                    tree = ast.parse(
                        path.read_text(encoding="utf-8"),
                        filename=str(path),
                    )
                except FileNotFoundError:
                    continue
                except (SyntaxError, UnicodeError) as exc:
                    findings.append(
                        GateFinding(
                            self.gate_id,
                            GateSeverity.ERROR,
                            "STATIC_UNIT_SOURCE_INVALID",
                            f"{path.relative_to(root)}: {exc}",
                        )
                    )
                    continue
                for node in ast.walk(tree):
                    if not isinstance(node, ast.ClassDef):
                        continue
                    name = node.name
                    retired = name in _RETIRED_STATIC_CARRIERS
                    suspicious = (
                        name.endswith(_FORBIDDEN_SUFFIXES)
                        and not any(token in name for token in _DYNAMIC_NAME_TOKENS)
                    )
                    if not retired and not suspicious:
                        continue
                    findings.append(
                        GateFinding(
                            self.gate_id,
                            GateSeverity.ERROR,
                            (
                                "RETIRED_STATIC_CARRIER"
                                if retired
                                else "STATIC_SECOND_CARRIER"
                            ),
                            f"{path.relative_to(root)}:{node.lineno}:{name}",
                        )
                    )
        return GateReport(self.gate_id, tuple(findings))


__all__ = ["StaticUnitSemanticsGate"]

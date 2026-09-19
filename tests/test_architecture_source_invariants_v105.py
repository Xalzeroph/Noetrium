from tests_support import repository_architecture_report
import tempfile
import unittest
from pathlib import Path

from noetrium_platform.foundation.governance.architecture import audit_source_invariants


class ArchitectureSourceInvariantsV105Tests(unittest.TestCase):
    def test_current_tree_has_no_source_invariant_violation(self):
        root=Path(__file__).resolve().parents[1]
        self.assertEqual(audit_source_invariants(root),())
        self.assertEqual(repository_architecture_report().source_invariant_violations,())

    def test_effect_journal_core_cannot_import_environment_or_capability_domains(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); journal=root/'noetrium_platform/infrastructure/reliability/effect/runtime'; journal.mkdir(parents=True)
            (journal/'contracts.py').write_text(
                'from noetrium_platform.capabilities.environment.runtime.api import ActionRequest\n'
                'from noetrium_platform.capabilities.participant.capability.api import CapabilityRequest\n',
                encoding='utf-8',
            )
            rows=audit_source_invariants(root)
            invariants={x.invariant for x in rows}
            self.assertIn('effect_journal_domain_firewall', invariants)

    def test_forensics_cannot_reintroduce_failure_contract_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); forensic=root/'noetrium_platform/infrastructure/reliability/forensics'; forensic.mkdir(parents=True)
            (forensic/'redaction.py').write_text('def redact_text(value): return value\n', encoding='utf-8')
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='failure_contract_authority' for x in rows))

    def test_domain_logic_cannot_import_forensic_implementation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); workflow=root/'noetrium_platform/research/execution/workflow/implementations/context_action'; workflow.mkdir(parents=True)
            (workflow/'bad.py').write_text(
                'from noetrium_platform.infrastructure.reliability.forensics import ForensicStore\n', encoding='utf-8'
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='failure_forensics_dependency_direction' for x in rows))

    def test_observability_api_cannot_import_concrete_backend(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); api=root/'noetrium_platform/evidence/observability/api'; api.mkdir(parents=True)
            (api/'bad.py').write_text(
                'from noetrium_platform.infrastructure.reliability.forensics import ForensicStore\n', encoding='utf-8'
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='observability_api_backend_firewall' for x in rows))

    def test_domain_logic_cannot_import_effect_journal_implementation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); workflow=root/'noetrium_platform/research/execution/workflow/implementations/context_action'; workflow.mkdir(parents=True)
            (workflow/'bad.py').write_text(
                'from noetrium_platform.infrastructure.reliability.effect.runtime import SQLiteEffectIntentJournal\n',
                encoding='utf-8',
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='effect_contract_dependency_direction' for x in rows))

    def test_effect_journal_has_no_environment_compatibility_exception(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); journal=root/'noetrium_platform/infrastructure/reliability/effect/runtime'; journal.mkdir(parents=True)
            (journal/'action_compat.py').write_text(
                'from noetrium_platform.capabilities.environment.runtime.api import ActionRequest\n', encoding='utf-8'
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='effect_journal_domain_firewall' for x in rows))

    def test_model_os_cannot_reintroduce_parallel_host_inventory(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); model_os=root/'noetrium_platform/capabilities/model/serving'; model_os.mkdir(parents=True)
            (model_os/'placement.py').write_text(
                'class HostInventory:\n    pass\n\nclass TopologyPlanner:\n    pass\n',
                encoding='utf-8',
            )
            rows=audit_source_invariants(root)
            violations=[x for x in rows if x.invariant=='model_os_inventory_authority']
            self.assertEqual(len(violations),2)

    def test_fixed_participant_session_args_cannot_return_to_trial_executor(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); study=root/'noetrium_platform/research/experimentation/experiment/runtime'; study.mkdir(parents=True)
            (study/'trial_cycle.py').write_text(
                "class ExperimentTrialCycleExecutor:\n"
                "    def execute(self, participant_sessions, method_session=None):\n"
                "        pass\n",
                encoding='utf-8',
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='generic_participant_execution_signature' for x in rows))


    def test_composition_families_cannot_cross_import_specialized_domains(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); composition=root/'noetrium_platform/composition'; composition.mkdir(parents=True)
            (composition/'context_action.py').write_text(
                'from noetrium_platform.capabilities.participant.agent.api import AgentSession\n', encoding='utf-8'
            )
            (composition/'agent_turn.py').write_text(
                'from noetrium_platform.capabilities.participant.method.api import MethodSession\n', encoding='utf-8'
            )
            rows=audit_source_invariants(root)
            invariants={x.invariant for x in rows}
            self.assertIn('composition_context_action_firewall', invariants)
            self.assertIn('composition_agent_turn_firewall', invariants)

    def test_participant_bridge_cannot_import_unrelated_specialized_abi(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); participants=root/'noetrium_platform/composition/participants'; participants.mkdir(parents=True)
            (participants/'method.py').write_text(
                'from noetrium_platform.capabilities.participant.agent.api import AgentSession\n', encoding='utf-8'
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='participant_method_bridge_firewall' for x in rows))

    def test_production_code_cannot_import_composition_root(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); package=root/'noetrium_platform'; package.mkdir(parents=True)
            (package/'bad.py').write_text('import noetrium_platform.composition\n', encoding='utf-8')
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='composition_root_import_firewall' for x in rows))








    def test_participant_api_cannot_import_study_orchestration(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); api=root/'noetrium_platform/capabilities/participant/core/api'; api.mkdir(parents=True)
            (api/'bad.py').write_text(
                'from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec\n', encoding='utf-8'
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='participant_api_orchestration_firewall' for x in rows))

    def test_participant_api_cannot_import_concrete_implementation_package(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); api=root/'noetrium_platform/capabilities/participant/core/api'; api.mkdir(parents=True)
            (api/'bad.py').write_text(
                'from noetrium_platform.capabilities.participant.definition.runtime.catalog import ParticipantImplementationCatalog\n',
                encoding='utf-8',
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='participant_api_implementation_firewall' for x in rows))

    def test_participant_implementation_cannot_import_runtime_orchestration(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); impl=root/'noetrium_platform/capabilities/participant/definition/runtime'; impl.mkdir(parents=True)
            (impl/'bad.py').write_text(
                'from noetrium_platform.infrastructure.lifecycle.launch_control.control_plane import RuntimeControlPlane\n', encoding='utf-8'
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='participant_implementation_orchestration_firewall' for x in rows))

    def test_combined_runtime_participant_abstraction_cannot_return(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); api=root/'noetrium_platform/capabilities/participant/core/api'; api.mkdir(parents=True)
            (api/'contracts.py').write_text(
                'class RuntimeParticipant:\n    def open_session(self): pass\n', encoding='utf-8'
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='participant_combined_runtime_forbidden' for x in rows))

    def test_runtime_binding_must_freeze_implementation_and_runtime_separately(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); api=root/'noetrium_platform/capabilities/participant/core/api'; api.mkdir(parents=True)
            (api/'contracts.py').write_text(
                'class ParticipantRuntimeBinding:\n'
                '    role: str\n'
                '    implementation: object\n'
                '    configuration_digest: str\n',
                encoding='utf-8',
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='participant_runtime_binding_identity' for x in rows))

    def test_study_coordinator_cannot_import_concrete_participant_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); study=root/'noetrium_platform/research/experimentation/experiment'; study.mkdir(parents=True)
            (study/'run_coordination.py').write_text(
                'from noetrium_platform.capabilities.participant.session.runtime import ParticipantSessionRuntimeCatalog\n',
                encoding='utf-8',
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='experiment_runtime_implementation_boundary' for x in rows))

    def test_workflow_cannot_import_study_orchestration(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); workflow=root/'noetrium_platform/research/execution/workflow/implementations/context_action'; workflow.mkdir(parents=True)
            (workflow/'bad.py').write_text(
                'from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime\n', encoding='utf-8'
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='workflow_contract_dependency_direction' for x in rows))

    def test_workflow_cannot_import_runtime_implementation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); workflow=root/'noetrium_platform/research/execution/workflow/implementations/agent_turn'; workflow.mkdir(parents=True)
            (workflow/'bad.py').write_text(
                'from noetrium_platform.research.execution.workflow.runtime import KernelOperationDispatcher\n', encoding='utf-8'
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='workflow_contract_dependency_direction' for x in rows))

    def test_implementation_catalog_cannot_own_session_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); impl=root/'noetrium_platform/capabilities/participant/definition/runtime'; impl.mkdir(parents=True)
            (impl/'catalog.py').write_text(
                'class ParticipantImplementationCatalog:\n'
                '    def open_session(self): pass\n',
                encoding='utf-8',
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='participant_session_lifecycle_authority' for x in rows))


    def test_recovery_lease_store_cannot_own_execution_fencing(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); runtime=root/'noetrium_platform/infrastructure/reliability/recovery/providers'; runtime.mkdir(parents=True)
            (runtime/'lease_store.py').write_text(
                'class RecoveryLeaseStore:\n    def execution(self): pass\n',
                encoding='utf-8',
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='recovery_execution_authority' for x in rows))

    def test_release_quiescence_verifier_cannot_import_runtime_backends(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); bootstrap=root/'noetrium_platform/foundation/governance/release/composition'; bootstrap.mkdir(parents=True)
            (bootstrap/'retirement.py').write_text(
                'from noetrium_platform.infrastructure.lifecycle.service.runtime.quiescence import ExactServiceQuiescenceProbe\n',
                encoding='utf-8',
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='release_quiescence_backend_firewall' for x in rows))

    def test_prompt_publication_cannot_construct_or_infer_durable_stores(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); prompt=root/'noetrium_platform/capabilities/model/request/prompt/runtime'; prompt.mkdir(parents=True)
            (prompt/'publication.py').write_text(
                'def bad(root): return PromptGenerationStore(root / "generations")\n',
                encoding='utf-8',
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='prompt_publication_storage_boundary' for x in rows))

    def test_runtime_control_state_cannot_infer_history_backend(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); runtime=root/'noetrium_platform/research/execution/runtime/manager'; runtime.mkdir(parents=True)
            (runtime/'state.py').write_text(
                'from .history import RuntimeHistory\n'
                'def bad(path): return RuntimeHistory(path.with_name(path.name + ".history"))\n',
                encoding='utf-8',
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='runtime_state_history_boundary' for x in rows))

    def test_runtime_semantics_cannot_import_concrete_state_or_history_backend(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); runtime=root/'noetrium_platform/research/execution/runtime/manager'; runtime.mkdir(parents=True)
            (runtime/'status_readers.py').write_text(
                'from .runtime_state_storage import FileRuntimeControlStateStore\n'
                'def bad(store): return store.path\n',
                encoding='utf-8',
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='runtime_state_history_backend_boundary' for x in rows))

    def test_service_start_authority_cannot_derive_intent_storage_from_state_path(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); service=root/'noetrium_platform/infrastructure/lifecycle/service/runtime'; service.mkdir(parents=True)
            (service/'start_coordination.py').write_text(
                'from .start_intent_store import DirectoryServiceStartIntentStore\n'
                'def bad(path): return path.with_name(path.name + ".start-intents")\n',
                encoding='utf-8',
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='service_start_storage_boundary' for x in rows))

    def test_one_click_runtime_cannot_import_concrete_recovery_backend(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); runtime=root/'noetrium_platform/research/execution/runtime/manager'; runtime.mkdir(parents=True)
            (runtime/'one_click.py').write_text(
                'from noetrium_platform.infrastructure.reliability.recovery.execution.runtime.file_lock import FileLockedRecoveryExecutionFactory\n',
                encoding='utf-8',
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='recovery_execution_authority' for x in rows))


    def test_operator_cannot_import_forensic_or_telemetry_backend(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); operator=root/'noetrium_platform/product/operator'; operator.mkdir(parents=True)
            (operator/'routes.py').write_text(
                'from noetrium_platform.infrastructure.reliability.forensics import ForensicStore\n'
                'from noetrium_platform.evidence.observability.telemetry.metric.providers import SQLiteTelemetryReader\n',
                encoding='utf-8',
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='operator_diagnostic_backend_firewall' for x in rows))

    def test_diagnostics_service_cannot_import_forensic_backend(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); diagnostics=root/'noetrium_platform/infrastructure/reliability/diagnostics/runtime'; diagnostics.mkdir(parents=True)
            (diagnostics/'bad.py').write_text(
                'from noetrium_platform.infrastructure.reliability.forensics import ForensicStore\n', encoding='utf-8'
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='diagnostics_service_dependency_direction' for x in rows))

    def test_operator_cannot_reintroduce_diagnostic_algorithm_module(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); operator=root/'noetrium_platform/product/operator'; operator.mkdir(parents=True)
            (operator/'diagnosis.py').write_text('class FailureDiagnosisService: pass\n', encoding='utf-8')
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='diagnostics_authority_location' for x in rows))

    def test_forensics_cannot_reintroduce_failure_fingerprint_semantics(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); forensics=root/'noetrium_platform/infrastructure/reliability/forensics'; forensics.mkdir(parents=True)
            (forensics/'fingerprint.py').write_text('def fingerprint_failure(x): return x\n', encoding='utf-8')
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='diagnostics_authority_location' for x in rows))


    def test_error_api_cannot_depend_on_failure_or_forensic_layers(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); api=root/'noetrium_platform/foundation/kernel/kernel/errors'; api.mkdir(parents=True)
            (api/'bad.py').write_text('from noetrium_platform.infrastructure.reliability.failure.api import FailureEnvelope\n', encoding='utf-8')
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='error_api_dependency_firewall' for x in rows))

    def test_operator_cannot_surface_raw_exception_text(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); operator=root/'noetrium_platform/product/operator'; operator.mkdir(parents=True)
            (operator/'bad.py').write_text('def x(exc):\n    return {"error":str(exc)}\n', encoding='utf-8')
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='error_semantic_authority' for x in rows))



    def test_operator_cannot_surface_exception_via_fstring(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); operator=root/'noetrium_platform/product/operator'; operator.mkdir(parents=True)
            (operator/'bad.py').write_text(
                'def x():\n    try: raise RuntimeError()\n    except Exception as exc:\n        return f"failed: {exc}"\n',
                encoding='utf-8',
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='error_semantic_authority' for x in rows))

    def test_status_api_cannot_depend_on_operator_or_runtime_implementation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); api=root/'noetrium_platform/evidence/observability/status/api'; api.mkdir(parents=True)
            (api/'bad.py').write_text(
                'from noetrium_platform.product.operator.runtime_status import JoinedRuntimeStatusService\n',
                encoding='utf-8',
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='status_recovery_contract_firewall' for x in rows))

    def test_runtime_recovery_planner_cannot_import_execution_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); diagnostics=root/'noetrium_platform/infrastructure/reliability/diagnostics/runtime'; diagnostics.mkdir(parents=True)
            (diagnostics/'runtime_recovery.py').write_text(
                'from noetrium_platform.infrastructure.lifecycle.launch_control.one_click import OneClickRuntimeManager\n',
                encoding='utf-8',
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='runtime_recovery_planner_purity' for x in rows))

    def test_operator_status_contract_module_cannot_return(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); operator=root/'noetrium_platform/product/operator'; operator.mkdir(parents=True)
            (operator/'status.py').write_text('class PlatformStatus: pass\n', encoding='utf-8')
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='status_contract_authority' for x in rows))


    def test_operator_status_join_cannot_import_runtime_state_machine(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); operator=root/'noetrium_platform/product/operator'; operator.mkdir(parents=True)
            (operator/'status_service.py').write_text(
                'from noetrium_platform.infrastructure.lifecycle.launch_control.state import RuntimeControlStore\n',
                encoding='utf-8',
            )
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='status_projection_authority' for x in rows))

    def test_operator_cannot_reintroduce_runtime_status_projector(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); operator=root/'noetrium_platform/product/operator'; operator.mkdir(parents=True)
            (operator/'runtime_status_runtime.py').write_text('def snapshot(): pass\n', encoding='utf-8')
            rows=audit_source_invariants(root)
            self.assertTrue(any(x.invariant=='status_projection_authority' for x in rows))


if __name__=='__main__':
    unittest.main()

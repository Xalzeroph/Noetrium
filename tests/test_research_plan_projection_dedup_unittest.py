"""Pure recursive Unit projections are each evaluated once per research plan."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from noetrium_platform.foundation.kernel.structure import structure_unit
from noetrium_platform.research.experimentation.api import research_compiler as c


class ResearchPlanProjectionDedupTests(unittest.TestCase):
    def test_research_plan_reuses_semantically_identical_unit_projections(self):
        definition = structure_unit('study-test', traits=('research.study',))
        resolution = SimpleNamespace(resolution_digest='resolution-id')
        binding = SimpleNamespace(contribution_digest='binding-id', assurance_gaps=())
        values = {
            '_validate_binding_contribution': None,
            '_trial_provider_id': 'provider',
            '_protocol': 'protocol',
            'study_execution_plan': 'execution-plan',
            'study_seeds': (),
            '_experiment': 'experiment',
            '_schedule': ('schedule', 'topology', 'schedule-digest'),
            'study_binding_requirements': 'requirements',
            'binding_requirements_topology': 'requirements-topology',
            'study_protocol_variant_space': SimpleNamespace(unit_digest='variant-space'),
            '_revision_digest': 'revision',
            'study_trial_protocol': 'trial-protocol',
            '_method_implementation_digest': 'implementation',
            'study_definition_digest': 'definition-digest',
            'study_scientific_design_digest': 'science-digest',
            'study_participant_design_digest': 'participant-digest',
            'study_binding_requirement_digest': 'requirements-digest',
            'study_execution_policy_digest': 'execution-policy-digest',
            'study_benchmark': 'benchmark',
            'benchmark_cut_digest': 'benchmark-digest',
            'study_plan_digest': 'study-plan-digest',
            'experiment_identity_digest': 'experiment-digest',
            'study_measurement_protocol': 'measurement-protocol',
            'measurement_protocol_semantic_digest': 'measurement-digest',
            'trial_protocol_digest': 'trial-protocol-digest',
            'study_execution_policy': 'execution-policy',
            'execution_policy_replay_level': 'full',
        }
        calls = {name: Mock(return_value=value) for name, value in values.items()}
        calls['run_research_semantics_unit'] = Mock(side_effect=lambda **kw: kw)
        calls['research_plan_graph'] = Mock(side_effect=lambda **kw: kw)
        with patch.multiple(c, **calls):
            plan = c.compile_research_plan(definition, resolution, binding)
        semantics = plan['semantics']
        self.assertEqual(plan['definition_digest'], 'definition-digest')
        self.assertEqual(plan['study_plan_digest'] if 'study_plan_digest' in plan else semantics['study_plan_digest'], 'study-plan-digest')
        self.assertEqual(plan['measurement_semantics_digest'], 'measurement-digest')
        self.assertEqual(semantics['measurement_protocol_digest'], 'measurement-digest')
        self.assertEqual(plan['experiment_digest'], 'experiment-digest')
        for name in (
            'study_definition_digest', 'study_scientific_design_digest',
            'study_participant_design_digest', 'study_binding_requirement_digest',
            'study_plan_digest', 'experiment_identity_digest',
            'measurement_protocol_semantic_digest', 'trial_protocol_digest',
        ):
            self.assertEqual(calls[name].call_count, 1, name)


if __name__ == '__main__':
    unittest.main()

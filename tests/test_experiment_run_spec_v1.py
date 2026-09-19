from __future__ import annotations

import unittest
from dataclasses import dataclass, replace

from noetrium_platform.research.experimentation.api import ProjectRunDefinition
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec
from noetrium_platform.research.experimentation.run.api import ExperimentRunSpec
from noetrium_platform.research.experimentation.run.identity.api import RunIdentity
from noetrium_platform.research.experimentation.identity import OptionalIdentityFacet, ReplayLevel
from noetrium_platform.research.experimentation.run.manifest.api import CompositionPlanReference, RunLaunchManifest, RunResearchSemanticsReference
from noetrium_platform.research.experimentation.study.api import StudyConcurrencyPolicy, StudyProtocol, StudyVariantSpec, VariantKind
from tests_support import model_role_for_test


@dataclass(frozen=True)
class _ProjectIdentity:
    project_id: str


@dataclass(frozen=True)
class _ProjectManifest:
    identity: _ProjectIdentity
    semantic_digest: str
    study_ids: tuple[str, ...]


class ExperimentRunSpecTests(unittest.TestCase):
    def test_identity_is_environment_neutral_and_digestable(self) -> None:
        spec = ExperimentRunSpec(
            run_id="run-1",
            project_id="project-1",
            experiment_id="experiment-1",
            study_id="study-1",
            execution_profile="baseline",
            task_manifest_digest="1" * 64,
            seed_schedule_digest="2" * 64,
            repetitions=2,
            artifact_root="runs/project-1/run-1",
            environment_identity_digest="3" * 64,
            model_roles_digest="4" * 64,
        )

        self.assertEqual(len(spec.identity_digest()), 64)
        self.assertEqual(spec.repetitions, 2)


    def _project_run_definition(self) -> ProjectRunDefinition:
        seed = "e" * 64
        tasks = "f" * 64
        experiment = ExperimentSpec(
            "experiment-1", "study-1", "project-1", (), (model_role_for_test(),),
            "b" * 64, seed, 2, "workflow.v1", "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
        )
        study = StudyProtocol(
            "study-1", "workload-1",
            (StudyVariantSpec("control", VariantKind.CONTROL, "impl", "d" * 64),),
            2, seed, ("score",), tasks,
            ("standard",),
            StudyConcurrencyPolicy.serial_shared_v1(repetition_timeout_seconds=3600.0),
        )
        run = ExperimentRunSpec(
            "run-1", "project-1", "experiment-1", "study-1", "baseline",
            tasks, seed, 2, "runs/run-1", "7" * 64, experiment.model_roles_digest,
        )
        identity = RunIdentity("run-1", "session-1", "trace-1")
        project_manifest = _ProjectManifest(_ProjectIdentity("project-1"), "9" * 64, ("study-1",))
        manifest = RunLaunchManifest(
            "release", "prompt-generation", "prompt-promotion", "models", (), "host",
            "participant-impl", "participant-runtime", "participant-bindings",
            project_manifest.semantic_digest, experiment.identity_digest(),
            RunResearchSemanticsReference(
                research_plan_digest="1" * 64, study_plan_digest="2" * 64,
                measurement_protocol_digest="3" * 64, trial_protocol_digest="4" * 64,
                method_implementation_digest="0" * 64,
                intervention=OptionalIdentityFacet("5" * 64), topology=OptionalIdentityFacet(),
                participant_schedule=OptionalIdentityFacet(), revision=OptionalIdentityFacet("6" * 64),
                replay_level=ReplayLevel.EXACT,
            ),
            ("python", "-m", "demo"), "a" * 64, "b" * 64,
            (("project", "config"),), "seed-0",
            (CompositionPlanReference("plan", "owner", "scope", "c" * 64),),
        )
        return ProjectRunDefinition(project_manifest, experiment, study, run, identity, manifest)

    def test_project_run_definition_binds_public_identities_and_control_target(self) -> None:
        definition = self._project_run_definition()
        self.assertEqual(len(definition.definition_digest), 64)
        target = definition.control_target(3)
        self.assertEqual(target.run_id, definition.identity.run_id)
        self.assertEqual(target.run_manifest_digest, definition.manifest.digest())
        self.assertEqual(target.expected_generation, 3)

    def test_project_run_definition_rejects_cross_identity_drift(self) -> None:
        definition = self._project_run_definition()
        with self.assertRaisesRegex(ValueError, "project identity drifted"):
            ProjectRunDefinition(
                definition.project_manifest, definition.experiment, definition.study,
                replace(definition.run, project_id="project-other"),
                definition.identity, definition.manifest,
            )
        with self.assertRaisesRegex(ValueError, "launch manifest"):
            ProjectRunDefinition(
                definition.project_manifest, definition.experiment, definition.study,
                definition.run, definition.identity,
                replace(definition.manifest, experiment_spec_digest="wrong"),
            )

    def test_project_run_definition_rejects_project_manifest_binding_drift(self) -> None:
        definition = self._project_run_definition()
        with self.assertRaisesRegex(ValueError, "does not bind the ProjectManifest"):
            ProjectRunDefinition(
                definition.project_manifest, definition.experiment, definition.study,
                definition.run, definition.identity,
                replace(definition.manifest, project_manifest_digest="8" * 64),
            )
        undeclared = replace(definition.project_manifest, study_ids=("other-study",))
        with self.assertRaisesRegex(ValueError, "not declared by ProjectManifest"):
            ProjectRunDefinition(
                undeclared, definition.experiment, definition.study,
                definition.run, definition.identity, definition.manifest,
            )

    def test_empty_provider_identity_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ExperimentRunSpec(
                run_id="run-1",
                project_id="project-1",
                experiment_id="experiment-1",
                study_id="study-1",
                execution_profile="baseline",
                task_manifest_digest="1" * 64,
                seed_schedule_digest="2" * 64,
                repetitions=1,
                artifact_root="runs/project-1/run-1",
                environment_identity_digest="",
                model_roles_digest="4" * 64,
            )


if __name__ == "__main__":
    unittest.main()

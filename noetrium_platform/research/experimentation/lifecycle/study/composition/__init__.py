from ..algorithms import BasicStudyMetricAggregator
from ..providers import RunArtifactStudyPublication
from noetrium_platform.research.experimentation.lifecycle.run.api import RunArtifactStorePort
from .regrade import build_task_verifier_regrade_proof
from .research_result_source import StudyResearchResultSource


def build_run_study_publication(artifacts: RunArtifactStorePort) -> RunArtifactStudyPublication:
    return RunArtifactStudyPublication(artifacts)


__all__ = [
    "StudyResearchResultSource",
    "build_run_study_publication",
    "build_task_verifier_regrade_proof",
]

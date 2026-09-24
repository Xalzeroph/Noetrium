"""Run-local Artifact-store composition for Research OS Experiment execution."""
from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.lifecycle.run.composition.artifacts import (
    build_directory_run_artifact_store,
)

from .research_os_experiment import (
    ResearchOSExperimentArtifactStoreBinding,
    ResearchOSExperimentArtifactStoreFactoryPort,
    ResearchOSExperimentClosure,
)


class DirectoryResearchOSExperimentArtifactStoreFactory(
    ResearchOSExperimentArtifactStoreFactoryPort
):
    """Bind one deterministic directory-backed Artifact authority per execution cut.

    The factory owns no writer/executor implementation. All mutation is serialized
    through the injected TaskGroupPort and the canonical Run Artifact composition.
    """

    def __init__(
        self,
        root: Path,
        *,
        task_group: TaskGroupPort,
        queue_capacity: int | None = None,
    ) -> None:
        if type(root) is not Path:
            raise TypeError(
                "Research OS Experiment Artifact factory root must be pathlib.Path"
            )
        if not isinstance(task_group, TaskGroupPort):
            raise TypeError(
                "Research OS Experiment Artifact factory requires TaskGroupPort"
            )
        if queue_capacity is not None and (
            type(queue_capacity) is not int or queue_capacity <= 0
        ):
            raise ValueError(
                "Research OS Experiment Artifact queue_capacity must be positive"
            )
        resolved = root.expanduser().resolve()
        if resolved.exists() and (resolved.is_symlink() or not resolved.is_dir()):
            raise ValueError(
                "Research OS Experiment Artifact root must be a real directory"
            )
        resolved.mkdir(parents=True, exist_ok=True)
        self._root = resolved
        self._task_group = task_group
        self._queue_capacity = queue_capacity
        self._identity_digest = canonical_digest(
            {
                "schema": "research-os.experiment-artifact-store-factory.v1",
                "implementation": "directory-run-artifact-store",
                "root": str(resolved),
                "task_group_id": task_group.group_id,
                "queue_capacity": queue_capacity,
            }
        )

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    @property
    def root(self) -> Path:
        return self._root

    def resolve(
        self,
        closure: ResearchOSExperimentClosure,
        *,
        execution_cut_id: str,
    ) -> ResearchOSExperimentArtifactStoreBinding:
        if type(closure) is not ResearchOSExperimentClosure:
            raise TypeError(
                "Research OS Experiment Artifact resolution requires closure"
            )
        require_sha256(
            execution_cut_id,
            "Research OS Experiment Artifact execution_cut_id",
        )
        run_root = self._root / execution_cut_id
        artifacts = build_directory_run_artifact_store(
            run_root,
            run_id=execution_cut_id,
            task_group=self._task_group,
            queue_capacity=self._queue_capacity,
        )
        store_identity_digest = canonical_digest(
            {
                "schema": "research-os.experiment-artifact-store.v1",
                "factory_identity_digest": self._identity_digest,
                "execution_cut_id": execution_cut_id,
                "root": str(run_root),
                "run_id": execution_cut_id,
                "task_group_id": self._task_group.group_id,
            }
        )
        return ResearchOSExperimentArtifactStoreBinding(
            closure.closure_digest,
            execution_cut_id,
            artifacts,
            self._identity_digest,
            store_identity_digest,
        )


__all__ = ["DirectoryResearchOSExperimentArtifactStoreFactory"]

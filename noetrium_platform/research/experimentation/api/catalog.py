from __future__ import annotations

from typing import Protocol

from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.research.experimentation.lifecycle.run.api import RunIdentity


class ExperimentationCatalogPort(Protocol):
    """Rebuildable hierarchy projection over immutable Unit truth."""

    def register_study(self, spec: NoetriumUnit) -> None: ...
    def register_experiment(self, spec: NoetriumUnit) -> None: ...
    def register_run(self, experiment_id: str, identity: RunIdentity) -> None: ...
    def study(self, study_id: str) -> NoetriumUnit: ...
    def experiment(self, experiment_id: str) -> NoetriumUnit: ...
    def experiments(
        self,
        *,
        study_id: str | None = None,
    ) -> tuple[NoetriumUnit, ...]: ...


__all__ = ["ExperimentationCatalogPort"]

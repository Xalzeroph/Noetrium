from __future__ import annotations

import os
from pathlib import Path
import shutil

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.scope.path.api import ScopePathPort

from ..api import ResourceResolutionPort, ResourceResolutionRequest, ResolvedResourceBinding


class LocalResourceResolver(ResourceResolutionPort):
    """Resolve local paths and executables for one explicit request.

    It never starts a process or installs anything. Remote providers may
    implement the same Interface with target-host lookup semantics.
    """

    def __init__(self, path_resolver: ScopePathPort) -> None:
        self._paths = path_resolver

    def resolve(self, request: ResourceResolutionRequest) -> ResolvedResourceBinding:
        base = self._paths.normalize(request.base_path, flavor=request.flavor)
        resolved_paths: list[tuple[str, str]] = []
        for key, raw in request.paths:
            value = os.fspath(raw)
            if not self._paths.is_absolute(value):
                value = os.path.join(base, value)
            resolved_paths.append((key, self._paths.normalize(value, flavor=request.flavor)))

        resolved_executables: list[tuple[str, str]] = []
        for key, raw in request.executables:
            value = os.fspath(raw).strip()
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                located = shutil.which(value)
                if not located:
                    raise FileNotFoundError(f"resource executable is not resolvable: {value}")
                candidate = Path(located)
            if not candidate.is_file():
                raise FileNotFoundError(f"resource executable is not a regular file: {candidate}")
            resolved_executables.append((key, str(candidate.resolve())))

        return ResolvedResourceBinding(
            request.binding_id,
            request.flavor,
            tuple(resolved_paths),
            tuple(resolved_executables),
            canonical_digest(
                {
                    "binding_id": request.binding_id,
                    "flavor": request.flavor.value,
                    "paths": tuple(resolved_paths),
                    "executables": tuple(resolved_executables),
                }
            ),
        )


__all__ = ["LocalResourceResolver"]

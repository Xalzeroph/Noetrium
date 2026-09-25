from __future__ import annotations

import re

_PACKAGE = re.compile(r"[a-z][a-z0-9_]*")


def project_package_name(project_id: str) -> str:
    if type(project_id) is not str or not project_id.strip():
        raise ValueError("project_id must be non-empty text")
    package = project_id.replace("-", "_").replace(".", "_")
    if not _PACKAGE.fullmatch(package):
        raise ValueError("project_id cannot be normalized to a canonical Python package")
    return package


__all__ = ["project_package_name"]

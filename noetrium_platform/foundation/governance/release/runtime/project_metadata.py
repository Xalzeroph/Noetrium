from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True, slots=True)
class ProjectMetadata:
    name: str
    version: str
    python_requires: str
    source: str


def load_project_metadata(root: Path, *, allow_unversioned: bool = True) -> ProjectMetadata:
    """Resolve release identity from one project authority.

    Source trees use the root ``pyproject.toml``. A tree without that authority is
    explicitly unversioned when allowed; ambient metadata from the controller's
    installed package is never consulted, because it would create a second and
    potentially unrelated release authority.
    """

    root = Path(root)
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project = data.get("project", {})
        name = str(project.get("name") or "")
        version = str(project.get("version") or "")
        python_requires = str(project.get("requires-python") or "")
        if not name or not version or not python_requires:
            raise ValueError("pyproject.toml must define project.name, project.version, and project.requires-python")
        return ProjectMetadata(name, version, python_requires, "pyproject.toml")

    if not allow_unversioned:
        raise RuntimeError("project version authority not found")
    return ProjectMetadata("unversioned", "unversioned", ">=3.11", "synthetic")

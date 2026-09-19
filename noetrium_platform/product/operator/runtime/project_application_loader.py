from __future__ import annotations

from dataclasses import dataclass
import importlib
from pathlib import Path
import sys

from noetrium_platform.product.operator.api import (
    ProjectTemplateProfile, ResearchApplicationPort, project_template_revision,
)
from noetrium_platform.foundation.portfolio.api import ProjectManifest, decode_project_manifest_bytes

from .project_layout import project_package_name


@dataclass(frozen=True, slots=True)
class LoadedProjectApplication:
    project_root: Path
    manifest: ProjectManifest
    application: ResearchApplicationPort

    @property
    def default_target(self) -> str:
        return self.manifest.project.identity.project_id


def _project_manifest(root: Path) -> ProjectManifest:
    path = root / "project.manifest.json"
    if not path.is_file() or path.is_symlink():
        raise ValueError("project application requires canonical project.manifest.json")
    return decode_project_manifest_bytes(path.read_bytes())


def load_project_application(
    project_root: Path,
    *,
    config_path: Path | None = None,
) -> LoadedProjectApplication:
    root = project_root.expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("project application root must be a real directory")
    manifest = _project_manifest(root)
    profile = next((
        candidate for candidate in ProjectTemplateProfile
        if manifest.template_revision == project_template_revision(candidate)
    ), None)
    if profile is ProjectTemplateProfile.AUTHOR:
        raise ValueError(
            "author project exposes the public Research Method Host, not a runtime "
            "application; compile_method requires an injected BindingContribution, "
            "and execution requires an explicit provider/runtime application"
        )
    if profile is not ProjectTemplateProfile.PROVIDER:
        raise ValueError("project template revision is unsupported for lifecycle routing")
    package = project_package_name(manifest.project.identity.project_id)
    src = (root / "src").resolve()
    application_path = src / package / "application.py"
    if not application_path.is_file() or application_path.is_symlink():
        raise ValueError("project application module is missing")

    module_name = f"{package}.application"
    importlib.invalidate_caches()
    sys.path.insert(0, str(src))
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ValueError(f"cannot import project application module: {module_name}") from exc
    finally:
        if sys.path and sys.path[0] == str(src):
            sys.path.pop(0)

    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, str) or Path(module_file).resolve() != application_path.resolve():
        raise ValueError("project application module resolved outside the explicit project root")
    factory = getattr(module, "build_application", None)
    if not callable(factory):
        raise ValueError("project application must export callable build_application(config_path)")
    application = factory(config_path)
    if not callable(getattr(application, "execute", None)):
        raise TypeError("project build_application returned an invalid ResearchApplicationPort")
    return LoadedProjectApplication(root, manifest, application)


__all__ = ["LoadedProjectApplication", "load_project_application"]

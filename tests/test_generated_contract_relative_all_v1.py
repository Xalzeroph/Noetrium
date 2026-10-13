from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_generator():
    script = ROOT / "scripts/generate_downstream_contracts.py"
    spec = importlib.util.spec_from_file_location(
        "_noetrium_generate_contracts_relative_all_test",
        script,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_generator_resolves_relative_reexported_all_without_importing_project_code(
    tmp_path: Path,
) -> None:
    module = _load_generator()
    package = tmp_path / "pkg"
    api_dir = package / "api"
    api_dir.mkdir(parents=True)
    (package / "exported.py").write_text(
        '__all__ = ["Alpha", "beta"]\n',
        encoding="utf-8",
    )
    api = api_dir / "__init__.py"
    api.write_text(
        "from ..exported import __all__ as _exported_all\n"
        '__all__ = ["Local"]\n'
        "__all__ += list(_exported_all)\n",
        encoding="utf-8",
    )

    assert module._public_symbols(api) == ("Local", "Alpha", "beta")

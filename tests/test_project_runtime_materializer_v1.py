from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "materialize_project_runtime.py"
SPEC = importlib.util.spec_from_file_location("project_runtime_materializer", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
materializer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(materializer)


def _lock(*, base_image_id: str) -> dict:
    payload = {
        "schema": materializer._SCHEMA,
        "platform_version": "0.44.0",
        "python_version": "3.12.14",
        "base_image_id": base_image_id,
        "base_python_environment_digest": "a" * 64,
        "declaration_digest": "b" * 64,
        "platform_dependencies": [],
        "project_dependencies": ["networkx==3.5"],
        "packages": [
            {
                "name": "networkx",
                "canonical_name": "networkx",
                "version": "3.5",
                "sha256": "c" * 64,
            }
        ],
    }
    payload["lock_digest"] = materializer._digest(payload)
    return payload


def test_lock_is_bound_to_exact_base_image(tmp_path: Path) -> None:
    base = "sha256:" + "1" * 64
    lock = _lock(base_image_id=base)
    path = tmp_path / "project.dependencies.lock.json"
    path.write_bytes(materializer._canonical(lock) + b"\n")

    assert materializer._validated_existing_lock(
        path,
        declaration_digest="b" * 64,
        python_version="3.12.14",
        base_image_id=base,
    ) == lock
    assert materializer._validated_existing_lock(
        path,
        declaration_digest="b" * 64,
        python_version="3.12.14",
        base_image_id="sha256:" + "2" * 64,
    ) is None

    lock["packages"][0]["version"] = "3.6"
    path.write_bytes(materializer._canonical(lock) + b"\n")
    assert materializer._validated_existing_lock(
        path,
        declaration_digest="b" * 64,
        python_version="3.12.14",
        base_image_id=base,
    ) is None


def test_runtime_identity_covers_recipe_base_and_lock(tmp_path: Path) -> None:
    lock = _lock(base_image_id="sha256:" + "1" * 64)
    first = materializer._materialize_build_context(
        tmp_path,
        base_image_id="sha256:" + "1" * 64,
        lock=lock,
        recipe=b"FROM base\nRUN echo one\n",
    )
    second = materializer._materialize_build_context(
        tmp_path,
        base_image_id="sha256:" + "2" * 64,
        lock=lock,
        recipe=b"FROM base\nRUN echo one\n",
    )
    third = materializer._materialize_build_context(
        tmp_path,
        base_image_id="sha256:" + "1" * 64,
        lock=lock,
        recipe=b"FROM base\nRUN echo two\n",
    )

    assert len({first, second, third}) == 3
    first_root = tmp_path / "project-runtime" / "objects" / first
    assert (first_root / "Dockerfile").read_bytes() == b"FROM base\nRUN echo one\n"
    materialization = json.loads((first_root / "materialization.json").read_text())
    assert materialization["runtime_key"] == first
    assert materialization["base_image_id"] == "sha256:" + "1" * 64


def test_resolver_applies_exact_base_constraints(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **_: object) -> SimpleNamespace:
        constraints = Path(command[command.index("--constraint") + 1])
        assert constraints.read_text() == "httpx==0.28.1\nhuggingface_hub==1.33.0\n"
        report = Path(command[command.index("--report") + 1])
        report.write_text(
            json.dumps(
                {
                    "install": [
                        {
                            "metadata": {"name": "networkx", "version": "3.5"},
                            "download_info": {
                                "url": "https://example.invalid/networkx.whl",
                                "archive_info": {"hashes": {"sha256": "d" * 64}},
                            },
                        }
                    ]
                }
            )
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(materializer.subprocess, "run", fake_run)
    rows = materializer._resolve(
        ("networkx==3.5",),
        base_constraints=("httpx==0.28.1", "huggingface_hub==1.33.0"),
    )
    assert rows == (
        {
            "name": "networkx",
            "canonical_name": "networkx",
            "version": "3.5",
            "sha256": "d" * 64,
        },
    )


def test_project_requires_exact_platform_pin(tmp_path: Path) -> None:
    platform = tmp_path / "platform"
    project = tmp_path / "project"
    platform.mkdir()
    project.mkdir()
    (platform / "pyproject.toml").write_text(
        '[project]\nname="noetrium"\nversion="0.44.0"\ndependencies=["httpx>=0.28,<0.29"]\n'
    )
    (project / "pyproject.toml").write_text(
        '[project]\nname="paper"\nversion="1"\ndependencies=["noetrium==0.44.0","networkx==3.5"]\n'
    )

    version, extras, platform_dependencies = materializer._project_dependencies(
        project, platform
    )
    assert version == "0.44.0"
    assert extras == ("networkx==3.5",)
    assert platform_dependencies == ("httpx>=0.28,<0.29",)

    (project / "pyproject.toml").write_text(
        '[project]\nname="paper"\nversion="1"\ndependencies=["noetrium>=0.44.0"]\n'
    )
    with pytest.raises(RuntimeError, match="exact platform pin"):
        materializer._project_dependencies(project, platform)

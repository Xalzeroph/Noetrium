from __future__ import annotations

from pathlib import Path
import tomllib


def test_minecraft_bridge_assets_are_declared_as_package_data() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]
    patterns = set(package_data["noetrium_platform.capabilities.environment.minecraft.providers"])
    assert "assets/mineflayer_bridge/*.js" in patterns
    assert "assets/mineflayer_bridge/package.json" in patterns
    assert "assets/mineflayer_bridge/package-lock.json" in patterns


def test_minecraft_environment_image_is_project_agnostic() -> None:
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "deploy" / "environments" / "minecraft" / "Dockerfile").read_text(encoding="utf-8")
    compose = (root / "deploy" / "environments" / "minecraft" / "compose.yaml").read_text(encoding="utf-8")
    assert "ARG PLATFORM_BASE_IMAGE" in dockerfile
    assert "FROM ${PLATFORM_BASE_IMAGE}" in dockerfile
    assert "COPY noetrium" not in dockerfile
    assert "COPY research" not in dockerfile
    assert "COPY benchmarks" not in dockerfile
    assert "projects/" not in dockerfile.lower()
    assert "environment-doctor" in compose
    assert "minecraft" in compose

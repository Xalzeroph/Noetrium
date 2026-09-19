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


def test_minecraft_container_overlay_is_project_agnostic() -> None:
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "deploy" / "Dockerfile.minecraft").read_text(encoding="utf-8")
    compose = (root / "deploy" / "compose.minecraft.yaml").read_text(encoding="utf-8")
    assert "COPY projects" not in dockerfile
    assert "projects/" not in dockerfile.lower()
    assert "projects/" not in compose
    assert "minecraft-doctor" in compose

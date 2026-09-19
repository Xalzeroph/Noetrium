from __future__ import annotations

import hashlib
import json
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import canonical_digest

ROOT = Path(__file__).resolve().parents[1]


def test_every_reproduction_has_typed_authorities_and_generated_projection() -> None:
    packages = tuple(sorted(path for path in (ROOT / "research/reproductions").iterdir() if path.is_dir()))
    packages = tuple(path for path in packages if (path / "reproduction.json").is_file())
    assert len(packages) >= 36
    for package in packages:
        assert (package / "definition.py").is_file()
        assert (package / "source.py").is_file()
        document = json.loads((package / "reproduction.json").read_text(encoding="utf-8"))
        assert document["schema"] == "noetrium.reproduction.projection.v5"
        assert document["authority"] == "generated_from_typed_definition_and_source"
        assert document["package"] == package.name
        assert "scientific_contract" not in document
        assert "reproduction_status" not in document["catalog"]
        assert document["assets"]
        for asset in document["assets"]:
            assert set(asset) == {"kind", "path", "declaration_digest", "content_sha256"}
            payload = (ROOT / asset["path"]).read_bytes()
            assert asset["content_sha256"] == hashlib.sha256(payload).hexdigest()
        assert document["scientific_tests"]
        for scientific_test in document["scientific_tests"]:
            assert set(scientific_test) == {"path", "content_sha256"}
            payload = (ROOT / scientific_test["path"]).read_bytes()
            assert scientific_test["content_sha256"] == hashlib.sha256(payload).hexdigest()
        assert document["package_digest"] == canonical_digest(
            {
                "definition_digest": document["definition_digest"],
                "source_registry_digest": document["source_registry_digest"],
                "assets": document["assets"],
                "scientific_tests": document["scientific_tests"],
            }
        )


def test_artifact_only_reproduction_never_invents_executable_source() -> None:
    mars = json.loads(
        (ROOT / "research/reproductions/mars_automated_ai_research/reproduction.json")
        .read_text(encoding="utf-8")
    )
    assert mars["lifecycle"] == "artifact_only"
    executable = {"official_executable", "later_released_executable", "surrogate", "independent"}
    assert all(row["kind"] not in executable for row in mars["source_lanes"])

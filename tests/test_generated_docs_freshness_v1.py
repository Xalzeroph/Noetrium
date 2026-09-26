from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_updater():
    script = ROOT / "scripts/update_generated_docs.py"
    spec = importlib.util.spec_from_file_location(
        "_noetrium_update_generated_docs_freshness_test",
        script,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _readme(locale: str, stamp: str, body: str) -> str:
    return (
        f"<!-- readme-locale:{locale} -->\n"
        f"<!-- readme-source-sha256:{stamp} -->\n"
        f"{body}\n"
    )


def test_generated_docs_restamps_only_source_and_previously_current_translations(
    tmp_path: Path,
) -> None:
    module = _load_updater()
    manifest_dir = tmp_path / "docs/readme"
    manifest_dir.mkdir(parents=True)
    manifest = {
        "schema": "agent-noetrium.readme-languages.v1",
        "default": "en",
        "source": "README.md",
        "languages": [
            {"locale": "en", "name": "English", "file": "README.md", "tier": 0},
            {"locale": "zh-CN", "name": "简体中文", "file": "README.zh-CN.md", "tier": 1},
            {"locale": "es", "name": "Español", "file": "README.es.md", "tier": 2},
        ],
    }
    (manifest_dir / "LANGUAGES.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    source_digest = hashlib.sha256(b"source body\n").hexdigest()
    stale_digest = "1" * 64
    (tmp_path / "README.md").write_text(
        _readme("en", source_digest, "source body"),
        encoding="utf-8",
    )
    (tmp_path / "README.zh-CN.md").write_text(
        _readme("zh-CN", source_digest, "translated body"),
        encoding="utf-8",
    )
    (tmp_path / "README.es.md").write_text(
        _readme("es", stale_digest, "stale translated body"),
        encoding="utf-8",
    )

    assert module._readme_locales_to_restamp(tmp_path) == ("en", "zh-CN")

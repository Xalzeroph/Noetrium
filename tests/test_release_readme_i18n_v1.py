from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_readme_i18n_gate_is_current_for_all_supported_locales() -> None:
    checker = _load_script("check_readme_i18n")
    assert checker.validate_root(ROOT, require_all_current=True) == ()


def test_readme_semantic_digest_ignores_generated_navigation_and_freshness_metadata() -> None:
    maintenance = _load_script("readme_i18n")
    text = maintenance.read_utf8(ROOT / "README.md")
    expected = maintenance.semantic_source_digest(text)
    changed_nav = maintenance.NAV_RE.sub("<!-- readme-nav:start -->x<!-- readme-nav:end -->", text)
    changed_meta = maintenance.SOURCE_RE.sub("<!-- readme-source-sha256:" + "0" * 64 + " -->", changed_nav)
    assert maintenance.semantic_source_digest(changed_meta) == expected
    assert maintenance.semantic_source_digest(text.replace("Overview", "Overview changed", 1)) != expected


def test_language_navigation_is_fully_derived_from_registry() -> None:
    maintenance = _load_script("readme_i18n")
    manifest = maintenance.load_languages(ROOT)
    assert len(manifest["languages"]) == 10
    for row in manifest["languages"]:
        text = maintenance.read_utf8(ROOT / row["file"])
        match = maintenance.NAV_RE.search(text)
        assert match is not None
        assert match.group(0) == maintenance.render_navigation(manifest, row["locale"])


def test_every_locale_uses_the_same_stable_section_contract() -> None:
    maintenance = _load_script("readme_i18n")
    manifest = maintenance.load_languages(ROOT)
    schema = __import__("json").loads((ROOT / "docs/readme/README_SCHEMA.json").read_text(encoding="utf-8"))
    expected = tuple(schema["section_ids"])
    for row in manifest["languages"]:
        text = maintenance.read_utf8(ROOT / row["file"])
        assert maintenance.extract_sections(text) == expected

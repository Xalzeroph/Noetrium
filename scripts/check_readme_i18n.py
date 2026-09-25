from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from readme_i18n import (
    NAV_RE,
    current_source_digest,
    extract_locale,
    extract_sections,
    extract_source_digest,
    load_languages,
    read_utf8,
    render_navigation,
)

FENCE_RE = re.compile(r"```([^\n]*)\n(.*?)```", re.S)
LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
HTTP_PREFIXES = ("http://", "https://", "mailto:", "#")


def _load_json(path: Path) -> dict:
    return json.loads(read_utf8(path))

def _code_blocks(text: str) -> tuple[tuple[str, str], ...]:
    return tuple((lang.strip(), body) for lang, body in FENCE_RE.findall(text))


def _body_link_targets(text: str) -> tuple[str, ...]:
    without_nav = NAV_RE.sub("", text)
    return tuple(sorted(LINK_RE.findall(without_nav)))


def _check_relative_links(root: Path, file: Path, text: str) -> list[str]:
    errors = []
    for target in LINK_RE.findall(text):
        clean = target.split("#", 1)[0]
        if not clean or clean.startswith(HTTP_PREFIXES):
            continue
        candidate = (file.parent / clean).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            errors.append(f"{file.name}: relative link escapes repository: {target}")
            continue
        if not candidate.exists():
            errors.append(f"{file.name}: broken relative link: {target}")
    return errors


def _project_metadata(root: Path) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
    document = tomllib.loads(read_utf8(root / "pyproject.toml"))
    project = document["project"]
    build_requires = tuple(str(x) for x in document.get("build-system", {}).get("requires", ()))
    license_files = tuple(str(x) for x in project.get("license-files", ()))
    return str(project["version"]), str(project.get("license", "")), license_files, build_requires


def validate_root(root: Path = ROOT, *, require_all_current: bool = False) -> tuple[str, ...]:
    root = Path(root).resolve()
    errors: list[str] = []
    manifest = load_languages(root)
    schema = _load_json(root / "docs/readme/README_SCHEMA.json")
    state = _load_json(root / "docs/readme/TRANSLATION_STATE.json")
    rows = manifest.get("languages", [])
    locales = [row.get("locale") for row in rows]
    files = [row.get("file") for row in rows]
    if len(rows) != 10:
        errors.append(f"language registry must contain 10 locales, observed {len(rows)}")
    if len(locales) != len(set(locales)):
        errors.append("language registry contains duplicate locales")
    if len(files) != len(set(files)):
        errors.append("language registry contains duplicate README files")
    if manifest.get("default") != "en" or manifest.get("source") != "README.md":
        errors.append("English README.md must remain the default semantic source")

    expected_sections = tuple(schema.get("section_ids", ()))
    source_digest = current_source_digest(root)
    expected_nav = {row["locale"]: render_navigation(manifest, row["locale"]) for row in rows}
    text_by_locale: dict[str, str] = {}
    for row in rows:
        locale = row["locale"]
        path = root / row["file"]
        if not path.is_file():
            errors.append(f"missing locale README: {row['file']}")
            continue
        try:
            text = read_utf8(path)
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(str(exc))
            continue
        text_by_locale[locale] = text
        if extract_locale(text) != locale:
            errors.append(f"{row['file']}: locale marker mismatch")
        if extract_sections(text) != expected_sections:
            errors.append(f"{row['file']}: section IDs/order differ from README_SCHEMA.json")
        nav_match = NAV_RE.search(text)
        if nav_match is None or nav_match.group(0) != expected_nav[locale]:
            errors.append(f"{row['file']}: generated language navigation drift")
        errors.extend(_check_relative_links(root, path, text))

    if "en" in text_by_locale:
        source_blocks = _code_blocks(text_by_locale["en"])
        source_links = _body_link_targets(text_by_locale["en"])
        for row in rows:
            locale = row["locale"]
            text = text_by_locale.get(locale)
            if text is None:
                continue
            if _code_blocks(text) != source_blocks:
                errors.append(f"{row['file']}: fenced code blocks drift from README.md")
            if _body_link_targets(text) != source_links:
                errors.append(f"{row['file']}: body link targets drift from README.md")

    for row in rows:
        locale = row["locale"]
        text = text_by_locale.get(locale)
        if text is None:
            continue
        stamp = extract_source_digest(text)
        if locale == manifest["default"]:
            if stamp != source_digest:
                errors.append(f"{row['file']}: English source digest stamp drift")
            continue
        tier = int(row.get("tier", 2))
        must_be_current = require_all_current or tier <= 1
        if must_be_current and stamp != source_digest:
            errors.append(f"{row['file']}: translation stale for source {source_digest}")

    if state.get("source_semantic_sha256") != source_digest:
        errors.append("TRANSLATION_STATE.json source digest is stale")
    state_rows = state.get("translations", {})
    for row in rows:
        locale = row["locale"]
        state_row = state_rows.get(locale)
        if not isinstance(state_row, dict):
            errors.append(f"TRANSLATION_STATE.json missing locale {locale}")
            continue
        stamp = extract_source_digest(text_by_locale.get(locale, ""))
        if state_row.get("source_semantic_sha256") != stamp:
            errors.append(f"TRANSLATION_STATE.json stamp drift for {locale}")

    try:
        version, license_expression, license_files, build_requires = _project_metadata(root)
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        errors.append(f"pyproject metadata unreadable: {exc}")
    else:
        if license_expression != "Apache-2.0":
            errors.append(f"pyproject project.license must be Apache-2.0, observed {license_expression!r}")
        expected_license_files = ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md")
        if license_files != expected_license_files:
            errors.append(f"pyproject license-files drift: {license_files!r}")
        if not any(req.startswith("setuptools>=77") for req in build_requires):
            errors.append("build-system must require setuptools>=77 for SPDX/license-files metadata")
        badge_token = f"version-{version}-blue"
        if badge_token not in text_by_locale.get("en", ""):
            errors.append(f"README.md version badge does not match pyproject version {version}")
    for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"):
        if not (root / name).is_file():
            errors.append(f"missing release license artifact: {name}")
    license_text = read_utf8(root / "LICENSE") if (root / "LICENSE").is_file() else ""
    if "Apache License" not in license_text or "Version 2.0, January 2004" not in license_text:
        errors.append("LICENSE is not the canonical Apache License 2.0 text")
    return tuple(errors)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate multilingual README structure, freshness and release metadata.")
    parser.add_argument("--all-current", action="store_true", help="require Tier 2 translations to be current too")
    args = parser.parse_args(argv)
    try:
        errors = validate_root(ROOT, require_all_current=args.all_current)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        errors = (f"validator failure: {exc}",)
    if errors:
        print("README_I18N_CHECK_FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    manifest = load_languages(ROOT)
    schema = _load_json(ROOT / "docs/readme/README_SCHEMA.json")
    print("README_I18N_CHECK_PASS")
    print(f"languages={len(manifest['languages'])}")
    print(f"sections={len(schema['section_ids'])}")
    print(f"source_semantic_sha256={current_source_digest(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

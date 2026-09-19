from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
README_DIR = ROOT / "docs" / "readme"
LANGUAGES_PATH = README_DIR / "LANGUAGES.json"
STATE_PATH = README_DIR / "TRANSLATION_STATE.json"
NAV_RE = re.compile(r"<!-- readme-nav:start -->.*?<!-- readme-nav:end -->", re.S)
LOCALE_RE = re.compile(r"<!-- readme-locale:([^>]+) -->")
SOURCE_RE = re.compile(r"<!-- readme-source-sha256:([0-9a-f]{64}) -->")
SECTION_RE = re.compile(r"<!-- readme-section:([a-z0-9-]+) -->")


def load_languages(root: Path = ROOT) -> dict:
    return json.loads((root / "docs/readme/LANGUAGES.json").read_text(encoding="utf-8"))


def read_utf8(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"UTF-8 BOM is forbidden: {path}")
    text = raw.decode("utf-8")
    if "\ufffd" in text:
        raise ValueError(f"replacement character is forbidden: {path}")
    return text.replace("\r\n", "\n")

def semantic_source_digest(text: str) -> str:
    clean = NAV_RE.sub("", text)
    clean = re.sub(r"<!-- readme-(?:locale|source-sha256):.*?-->\n?", "", clean)
    clean = "\n".join(line.rstrip() for line in clean.split("\n")).strip() + "\n"
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


def extract_locale(text: str) -> str | None:
    match = LOCALE_RE.search(text)
    return None if match is None else match.group(1)


def extract_source_digest(text: str) -> str | None:
    match = SOURCE_RE.search(text)
    return None if match is None else match.group(1)


def extract_sections(text: str) -> tuple[str, ...]:
    return tuple(SECTION_RE.findall(text))


def render_navigation(manifest: dict, locale: str) -> str:
    items = []
    for row in manifest["languages"]:
        if row["locale"] == locale:
            items.append(f"<strong>{row['name']}</strong>")
        else:
            items.append(f'<a href="{row["file"]}">{row["name"]}</a>')
    return "<!-- readme-nav:start -->\n<p align=\"center\">\n  " + " ·\n  ".join(items) + "\n</p>\n<!-- readme-nav:end -->"


def replace_navigation(text: str, navigation: str) -> str:
    if not NAV_RE.search(text):
        raise ValueError("README is missing generated navigation markers")
    return NAV_RE.sub(navigation, text, count=1)

def sync_navigation(root: Path = ROOT) -> tuple[str, ...]:
    manifest = load_languages(root)
    changed: list[str] = []
    for row in manifest["languages"]:
        path = root / row["file"]
        text = read_utf8(path)
        updated = replace_navigation(text, render_navigation(manifest, row["locale"]))
        if updated != text:
            path.write_text(updated, encoding="utf-8", newline="\n")
            changed.append(row["file"])
    return tuple(changed)


def current_source_digest(root: Path = ROOT) -> str:
    manifest = load_languages(root)
    source = root / manifest["source"]
    return semantic_source_digest(read_utf8(source))


def translation_status(root: Path = ROOT) -> tuple[tuple[str, str, str | None], ...]:
    manifest = load_languages(root)
    source_digest = current_source_digest(root)
    rows = []
    for row in manifest["languages"]:
        text = read_utf8(root / row["file"])
        stamp = extract_source_digest(text)
        if row["locale"] == manifest["default"]:
            status = "SOURCE" if stamp == source_digest else "SOURCE_STAMP_DRIFT"
        else:
            status = "CURRENT" if stamp == source_digest else "STALE"
        rows.append((row["locale"], status, stamp))
    return tuple(rows)


def _replace_source_stamp(text: str, digest: str) -> str:
    if not SOURCE_RE.search(text):
        raise ValueError("README is missing source digest marker")
    return SOURCE_RE.sub(f"<!-- readme-source-sha256:{digest} -->", text, count=1)

def mark_current(locales: Iterable[str], root: Path = ROOT) -> tuple[str, ...]:
    manifest = load_languages(root)
    known = {row["locale"]: row for row in manifest["languages"]}
    requested = tuple(dict.fromkeys(locales))
    unknown = sorted(set(requested) - set(known))
    if unknown:
        raise ValueError(f"unknown locales: {', '.join(unknown)}")
    digest = current_source_digest(root)
    changed: list[str] = []
    for locale in requested:
        row = known[locale]
        path = root / row["file"]
        text = read_utf8(path)
        updated = _replace_source_stamp(text, digest)
        if updated != text:
            path.write_text(updated, encoding="utf-8", newline="\n")
            changed.append(row["file"])
    _write_state(root, digest)
    return tuple(changed)


def _write_state(root: Path, source_digest: str | None = None) -> None:
    manifest = load_languages(root)
    digest = source_digest or current_source_digest(root)
    translations = {}
    for row in manifest["languages"]:
        stamp = extract_source_digest(read_utf8(root / row["file"]))
        if row["locale"] == manifest["default"]:
            status = "source" if stamp == digest else "source-stamp-drift"
        else:
            status = "current" if stamp == digest else "stale"
        translations[row["locale"]] = {"status": status, "source_semantic_sha256": stamp}
    state = {
        "schema": "agent-noetrium.readme-translation-state.v1",
        "source_locale": manifest["default"],
        "source_semantic_sha256": digest,
        "translations": translations,
    }
    (root / "docs/readme/TRANSLATION_STATE.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Maintain multilingual README navigation and freshness state.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("source-digest")
    sub.add_parser("sync-navigation")
    mark = sub.add_parser("mark-current")
    mark.add_argument("locales", nargs="+")
    args = parser.parse_args(argv)
    try:
        if args.command == "source-digest":
            print(current_source_digest())
            return 0
        if args.command == "sync-navigation":
            changed = sync_navigation()
            print(f"README_I18N_NAVIGATION_SYNC changed={len(changed)}")
            for path in changed:
                print(path)
            return 0
        if args.command == "mark-current":
            changed = mark_current(args.locales)
            print(f"README_I18N_MARK_CURRENT changed={len(changed)} source={current_source_digest()}")
            for path in changed:
                print(path)
            return 0
        rows = translation_status()
        for locale, status, stamp in rows:
            print(f"{locale:<7} {status:<18} {stamp or '-'}")
        return 1 if any(status in {"STALE", "SOURCE_STAMP_DRIFT"} for _, status, _ in rows) else 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"README_I18N_FAIL: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

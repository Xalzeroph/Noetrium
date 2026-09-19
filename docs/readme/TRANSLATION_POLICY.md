# README Translation Policy

## Authority

`README.md` is the semantic source of truth for the multilingual README system. Localized README files are Git-tracked translations, not runtime machine translations.

The authoritative software license is the root `LICENSE` file. Translated README license explanations are informational only.

## Locale policy

Locale identifiers and filenames are declared only in `docs/readme/LANGUAGES.json` and use BCP 47-style tags.

Tier 0: English source. Tier 1: Simplified Chinese, Traditional Chinese, Japanese, Korean. Tier 2: Spanish, Brazilian Portuguese, French, German, Russian.

A release requires Tier 0 and Tier 1 translations to be current. Tier 2 may be reported stale during development, but published release documentation should normally refresh all supported locales.

## Structural invariants

Every localized README must contain the same ordered `readme-section:*` identifiers declared by `README_SCHEMA.json`.
Code blocks, CLI commands, file paths, environment variables, JSON keys, API symbols, SHA digests and architecture node IDs are not translated.

Markdown link labels may be localized, but their destinations must remain structurally equivalent across locales. Relative links must resolve in the repository.

The language navigation block is generated from `LANGUAGES.json`; it must not be hand-maintained independently in ten files.

## Freshness

`readme-source-sha256` records the semantic digest of the English README after excluding navigation and freshness metadata.

Changing English semantic content changes that digest. A localized README remains stale until it is reviewed and explicitly stamped current with `scripts/readme_i18n.py mark-current <locale>`.

`sync-navigation` never changes freshness. This prevents a formatting command from falsely approving a translation.

## Translation quality

Translations should be natural in the target language while preserving technical meaning. Project name, contract names and technical tokens may remain in English when translation would weaken precision.

Use `docs/readme/GLOSSARY.json` for terms whose architecture meaning is narrower than ordinary-language translations.

## Verification

Run `python scripts/check_readme_i18n.py` during development and before release. Release evidence generation also invokes this gate directly.

# Multilingual README System

This directory governs the repository's localized public README surface.

## Files

- `LANGUAGES.json` — locale registry, filenames and maintenance tiers.
- `README_SCHEMA.json` — stable ordered section IDs and license invariants.
- `TRANSLATION_STATE.json` — source semantic digest and per-locale freshness.
- `TRANSLATION_POLICY.md` — authority, translation, freshness and release rules.
- `GLOSSARY.json` — architecture terms whose meaning must remain stable across translations.

The generated/public files remain at repository root so GitHub users can switch languages with one click:

```text
README.md
README.zh-CN.md
README.zh-TW.md
README.ja.md
README.ko.md
README.es.md
README.pt-BR.md
README.fr.md
README.de.md
README.ru.md
```

## Commands
```bash
python scripts/readme_i18n.py status
python scripts/readme_i18n.py sync-navigation
python scripts/readme_i18n.py mark-current zh-CN ja
python scripts/check_readme_i18n.py
python scripts/check_readme_i18n.py --all-current
```

`sync-navigation` changes only the generated language switcher. It never marks a translation current.

`mark-current` is explicit because freshness is a semantic review decision. Use it only after the named locale has been reviewed against the current English source.

## Release behavior

Tier 0 and Tier 1 translations must be current for release evidence generation. Tier 2 staleness is visible during development; `--all-current` can be used when preparing a fully synchronized public release.

The release manifest includes all README and i18n files automatically because release packaging hashes the complete non-excluded source tree.

`generate_release_evidence.py` invokes the multilingual README gate before generating release evidence, so structural drift cannot be hidden by unrelated green tests.

## Adding a locale

1. Register the BCP 47-style locale and root filename in `LANGUAGES.json`.
2. Add a localized README with the exact section IDs from `README_SCHEMA.json`.
3. Run `sync-navigation`.
4. Review technical terms against `GLOSSARY.json`.
5. Mark the translation current explicitly.
6. Run the i18n gate and release test.

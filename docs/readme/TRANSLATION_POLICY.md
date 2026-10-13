# README Translation Policy

`README.md` is the semantic source. Supported locales are declared only in `LANGUAGES.json`; the release does not require a fixed number of translations.

Every maintained translation must preserve the ordered section contract from `README_SCHEMA.json`, the fenced command/code blocks, and body link targets. The generated navigation comes from the locale registry.

A translation is current only when its `readme-source-sha256` matches the semantic digest of the English source. `sync-navigation` never approves semantic freshness; use `mark-current` only after review.

The root `LICENSE` is authoritative. Translated license descriptions are informational.

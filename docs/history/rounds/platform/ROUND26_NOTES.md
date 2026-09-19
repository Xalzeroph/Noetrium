# Round 26 — Prompt v6/v3 and Configuration No-Degradation Audit

## Objective

Strengthen the LLM-facing semantic contracts while making the no-quality-degradation rule executable across both source code and deployment configuration.

## Prompt changes

- `planner.v6`: freezes present-state evidence authority, historical-memory semantics, legal-tool authority, minimal progress and verifier-only completion.
- `semantic.v6`: accepts only memory-authorized evidence, preserves evidence IDs/temporal scope/conflicts and forbids private audit/evaluation evidence.
- `meta.v6`: remains a frozen structural reasoner with only `NO_EDIT/CREATE/RETIRE/SPLIT/MERGE`; transient latency, resource pressure, one-off retrieval misses and single failures are explicitly non-structural by themselves.
- `diagnostic.v3`: separates proven/correlated/unknown evidence, mutation state and external-effect certainty; recovery may never change model quality, context, prompt, method or scientific treatment.

Prompt output schemas remain unchanged where the contract was already sufficient. Runtime context overflow is still an explicit error/report, never silent truncation.

## No-Degradation Audit

The audit now scans:

- Python AST identifiers/attributes/literal keys;
- YAML/YML scalar policy switches;
- JSON nested configuration;
- TOML nested configuration.

Enabled `allow_*_downgrade/fallback` switches and non-empty fallback targets are hard findings. Explicit `false` values are allowed so frozen deployment manifests can prove the property.

## Validation

- `pytest`: 132 / 132 PASS
- Architecture Gate: PASS
- Silent-Failure Audit: PASS
- No-Degradation Audit: PASS
- Python compileall: PASS

No fallback model, lower precision, smaller context, truncated prompt, method substitution or sequential scientific-treatment replacement was introduced.

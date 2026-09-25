# Contributing to Noetrium

Thank you for helping improve reproducible AI-agent research infrastructure.

Noetrium values changes that are explicit about ownership, semantics, evidence, and failure behavior. A small, well-proven change is preferable to a broad refactor that hides unrelated effects.

## Choose the right channel

- **Bug or reproducible defect:** open a Bug Report issue.
- **Feature or design proposal:** open a Feature Request issue.
- **Question, idea, or open-ended design discussion:** use GitHub Discussions.
- **Security vulnerability:** follow `SECURITY.md`; do not disclose sensitive details in a public issue.

## Development setup

```bash
git clone https://github.com/Xalzeroph/noetrium.git
cd noetrium
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
```

## Before you change code

1. Identify the smallest subsystem that owns the behavior or durable state.
2. Prefer an existing public contract and a new provider over a new generic abstraction.
3. Keep project-specific research meaning downstream of the reusable platform.
4. Treat external effects, identity changes, and recovery behavior as explicit contract decisions.
5. If the change is intentionally breaking, make the semantic change explicit rather than adding hidden compatibility behavior.

## Single-mainline development

Platform changes are serialized in the canonical worktree and mainline. Do not create role-owned branches or long-lived role worktrees. Reviewers inspect commits read-only; they do not need a second worktree. The exact operating rules are in [`docs/development/SINGLE_MAINLINE_WORKFLOW.md`](docs/development/SINGLE_MAINLINE_WORKFLOW.md).

## Tests and evidence

Run focused tests first, then the gates appropriate to the affected boundary. Common checks are:

```bash
python -m pytest -q <focused tests>
python scripts/test_system.py check
python scripts/provider_conformance.py check
python scripts/product_assurance_gate.py --full --output product-assurance.json
python scripts/architecture_gate.py
python scripts/public_contract_audit.py
python scripts/no_degradation_audit.py
python scripts/silent_failure_audit.py
python scripts/check_readme_i18n.py
```

Do not describe a historical green run as evidence for a different revision. Test claims should identify the exact tree or commit they exercised.

## Documentation and multilingual README

`README.md` is the semantic source for the multilingual landing pages. If you change README structure, commands, code blocks, links, version metadata, or technical claims, update the localized files and run the i18n gate.

Do not manually edit generated language navigation outside the supported maintenance flow.

## Pull requests

Keep pull requests narrow enough to review as one semantic change. Include:

- the problem and intended outcome;
- affected ownership boundaries and public contracts;
- tests actually run and their results;
- recovery, persistence, concurrency, or external-effect implications when relevant;
- documentation changes required by the implementation.

Use the repository pull request template. Draft pull requests are welcome for early technical review, but they should not claim completion before their evidence is complete.

## Commit quality

Use clear, scoped commit messages and avoid mixing drive-by cleanup with the change under review. Keep local machine state, generated caches, and unrelated experiment output out of commits.

By contributing, you agree to follow `CODE_OF_CONDUCT.md` and the Apache-2.0 licensing terms for contributions to this repository.

Packaging or public-surface changes must additionally qualify installed distributions from a clean exact Git revision with `scripts/release_distribution.py`.

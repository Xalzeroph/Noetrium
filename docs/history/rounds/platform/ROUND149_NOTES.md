# Round 149 ? harden test identity and release diagnostics

Date: 2026-08-28

## Test-system identity

The repository now owns `tests` as an explicit Python package. Pytest adds both the repository root and `tests/` to its configured import path, preventing an installed third-party `tests` package from shadowing `tests._concurrency_support` while preserving the existing top-level test-helper ABI.

## Release diagnostics

Release-regression pytest output is captured as raw bytes and decoded with UTF-8 replacement semantics only for human diagnostics. Machine-readable pytest result JSON remains the release authority. This prevents Windows/local-codepage bytes emitted by child processes from aborting release generation with `UnicodeDecodeError` without weakening test-result validation.

## Verification

- Focused repository-boundary and Minecraft packaging tests: 9 passed.
- Fast hierarchical test gate: 227 passed, 1 skipped.
- Release-regression focused tests: 15 passed, 1 skipped.
- Complete repository regression after the fixes: 1083 passed, 6 skipped, 4 subtests passed.
- Architecture gate: pass; public-contract audit: zero weak contracts; no-degradation audit: pass.
- Repository boundary: zero violations; algorithm gate: 5732 symbols / 348 candidates; concurrency gate: 286 hotspots / 1 finding / 0 blocker debt; performance gate: 76 hotspots / 88 findings / 0 blocker debt.
- Mineflayer bridge after lockfile installation: 14/14 Node tests passed.

The release manifest walker also excludes `node_modules` as generated dependency-install state. A live manifest probe with the Mineflayer dependency tree still present produced 2894 release files and zero `node_modules` entries; the exclusion contract test passed together with the release-regression decoder tests (8 passed, 1 skipped).

Release evidence and package authority must be regenerated from this exact tree before 0.43.1 is considered published.

## Final upstream purity check

The pre-release identifier scan removed the last project-specific Core-6 wording from the generic Study API documentation. The tracked upstream tree contains no SEM project identifier, managed-server IP/path, or Qwen3.8 project-model identity.

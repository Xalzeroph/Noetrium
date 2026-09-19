# Forensics OS — Round 08

## Stable error taxonomy

Hot-path runtime code should select a registered `FailureSpec(domain, code, stage)` instead of inventing ad-hoc strings. The taxonomy also declares the default mechanical recovery and integrity/comparability/scientific risks.

## Secret-safe failures

Persisted exception messages and chained-cause fingerprints are redacted for high-confidence API-key/token/password forms before entering the failure ledger. Structured payload redaction recursively handles sensitive keys. Raw credentials are never needed for debugging identity, timing, state ownership or failure causality.

## Crash bundle

`CrashBundleBuilder` creates a small immutable manifest containing:

- the exact failure envelope;
- the correlated timeline window;
- recent authoritative state writers;
- verified tail hashes and row counts for event/failure/mutation ledgers;
- artifact references;
- one bundle SHA-256.

It does not duplicate large logs. Operators follow content-addressed/raw artifact references when deeper bytes are required.

## Silent failure audit

A source-level AST audit rejects high-confidence error-erasing constructs such as `except Exception: pass`, `except: continue`, bare-return broad catches and broad `contextlib.suppress(Exception)`. The policy is intentionally narrow: it detects silent loss, not every legitimate boundary catch.

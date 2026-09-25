# Round 16 — Segmented Structured Logs / Lossless Process Capture

- Global hash-chain structured events rotate across bounded files without resetting the chain.
- Derived segment manifest is rebuilt from authoritative bytes on verification.
- Added exact binary stdout/stderr capture with segment SHA-256 and absolute offsets.
- Arbitrary byte ranges can be re-read and verified; display tails no longer define retained evidence.

# Java Toolchain Provisioning

## Ownership

`runtime/toolchain` owns reproducible host toolchain acquisition, materialization, executable verification and the receipt that binds those facts. It does not own artifact bytes, environment semantics, server lifecycle, model deployment truth or scientific qualification.

The Temurin implementation is intentionally split by responsibility:

- `AdoptiumMetadataResolver` fetches and validates one exact upstream release identity.
- artifact content ports acquire and materialize the archive.
- `JavaRuntimeVerifier` verifies the materialized executable and exact Java major.
- the receipt codec persists a checksummed `JavaRuntimeReceipt`.
- `EclipseAdoptiumTemurinProvider` orchestrates those ports and owns no HTTP parsing or subprocess implementation details.

## Provisioning state machine

```text
request
  -> validated metadata identity
  -> content-addressed archive acquisition
  -> safe archive materialization
  -> java -version verification
  -> final tree inspection
  -> durable checksummed receipt
```

The receipt is written only after the materialized executable has passed exact-major verification and the post-verification tree has been inspected. This ordering captures distributions that perform one-time initialization during the first `java -version` invocation.
## Reuse and fail-closed recovery

A cached runtime is reusable only when the v2 receipt checksum is valid and every identity still matches the request: provider, feature version, OS, architecture, metadata URL, archive path, destination and Java executable. Reuse then re-hashes the archive and executable, executes `java -version`, and inspects the complete materialized tree again.

Any receipt corruption, archive drift, executable drift, version drift or tree drift fails closed. The provider does not silently redownload over an existing receipt or reinterpret a legacy receipt as current evidence. Breaking schema/provider identity changes therefore require explicit reprovisioning instead of permanent compatibility shims.

Metadata is treated as untrusted input inside one parser boundary. The resolver requires the current Adoptium v3 `version` shape, exact requested OS/architecture/JDK/HotSpot identity, an official `https://github.com/adoptium/temurin<major>-binaries/releases/download/...` asset, bounded names, positive size and a SHA-256 checksum. A similarly named or redirected package is not accepted as the requested toolchain.

## Failure and concurrency semantics

Provisioning is protected by an interprocess lock derived from the receipt path. Only one process may materialize or publish the same runtime identity at a time. The durable receipt is atomically replaced only after verification; a crash before receipt publication leaves no claim that the runtime is complete.

HTTP, archive and Java-command failures remain typed failures. A successful metadata request is not installation evidence, and a successful extraction is not Java identity evidence. Toolchain receipts are operational/runtime evidence only; downstream deployment and scientific qualification must bind them explicitly when those layers require them.

## Test placement

- L1 / WINDOWS: request, metadata, receipt and exact-version contracts.
- L2 / WINDOWS: deterministic provider composition with injected HTTP/command ports.
- L4 / BOTH: receipt corruption, reopen/reuse, interrupted publication and materialized-tree drift.
- L5 / BOTH: concurrent provisioning of the same receipt/destination identity.
- SERVER_TEST: real Linux Java materialization only when a deployment claim depends on the exact toolchain receipt.

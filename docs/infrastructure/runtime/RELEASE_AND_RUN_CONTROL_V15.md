# Release / Run Control — Round 15

## Hash-complete release identity

Every source/config/doc file in a release is listed with size + SHA-256. The release manifest has a tree digest. The deterministic ZIP normalizes entry order, timestamp and permissions, so building the same tree twice produces the same package bytes.

## Launch identity

`experimentation/run/manifest/api.RunLaunchManifest` is the single owner of
launch identity. Release contributes its digest to this record but does not
define a second run-manifest type. Runtime control consumes the narrow
`RuntimeLaunchManifestPort`, not the experiment package directly. The record
binds the parts that must not drift across a confirmatory run or exact recovery:

- release digest;
- prompt generation digest;
- role→model deployment manifest digest;
- Method ID/version/ABI;
- Environment ID/version/ABI;
- Study spec digest;
- target host fingerprint;
- exact launch argv;
- target launcher binary SHA-256;
- canonical digest of the controller environment (the values themselves are
  supplied only at launch and are never serialized into the manifest);
- config file digests;
- seed identity.

The run manifest also records canonical references to every capability
composition plan that formed the launch. A recovery therefore cannot attach a
new project/provider composition to an old controller process merely because
its release and study digests happen to match.

No secret values are serialized in the launch manifest. The server bootstrap
accepts no independent controller argv or launcher identity: it consumes the
frozen values above and rejects a supplied controller environment whose digest
does not match before any process side effect.

## Exact server startup plan

Startup is ordered as read-only identity verification → target inventory → qualified model service activation → READY → exact role canaries → Method/Environment ABI verification → Study start. Failure stops at the owning step; no fallback model or reduced configuration is selected.

# Log / Process Stream Capture — Round 16

## Segmented event hash-chain

High-volume structured events now use bounded `events.chain/00000000.jsonl`, `00000001.jsonl`, ... segments. The cryptographic chain **does not reset** at rotation. A segment gap, truncated JSON, previous-hash mismatch or row-hash mismatch identifies the exact segment/line.

`manifest.json` is derived acceleration metadata and is never trusted over segment bytes. Full verification rebuilds it.

## Byte-exact process output

`SegmentedByteCapture` is for model server / environment bridge stdout and stderr. It:

- stores raw bytes, not decoded/truncated tails;
- rotates at a fixed byte threshold;
- records absolute byte offsets per segment;
- seals every segment with SHA-256 and a manifest digest;
- reconstructs any requested byte range exactly;
- detects tampering/missing segments.

Operator UIs may show a short tail, but the tail is a **view** over lossless raw evidence, never the evidence boundary.

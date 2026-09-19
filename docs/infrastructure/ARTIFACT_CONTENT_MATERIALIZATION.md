# Artifact content materialization

`SafeTarArchiveMaterializer` extracts archives into a same-parent staging tree, validates
the complete planned topology, fsyncs materialized content/directories, and atomically
publishes the verified top-level tree. Destination publication remains fail closed: an
existing destination is never merged or overwritten.

## Owner-access invariant

Archive permission bits cannot make the staging tree inaccessible to the process that owns
materialization. Directories retain their declared group/other bits but always gain owner
`rwx`; regular files retain group/other bits but always gain owner `r`. This is required
so non-root Linux providers can validate required paths, resolve hardlinks, compute the
post-extraction tree digest, and publish the tree even when an archive declares mode
`000`. The provider does not grant permissions to group or other users that the archive
did not declare.

Regression qualification includes an explicit `mode=000` archive and verifies exact owner
access on POSIX after publication.

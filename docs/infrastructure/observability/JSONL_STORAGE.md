# JSONL storage concurrency contract

## Authority model

`JsonlLogStore` treats the caller-requested log path as a **logical storage authority**.
The active file may be renamed during rotation, but that rename must never change the
logical identity used for the writer actor or the cross-process guard.

The runtime therefore uses `logical_absolute_path()` rather than `Path.resolve()`.
The former anchors the requested pathname lexically without dereferencing the current
filesystem leaf. This matters on Windows because resolving a file while another process
renames it can observe the renamed file object and return a rotated-segment pathname.

## Typed port coupling

`JsonlLogStore` satisfies the logging sink/query Protocols structurally rather than
nominally inheriting the Protocol classes. The runtime therefore keeps the same typed
`append()`/`query()` contract without adding implementation-to-Protocol inheritance
edges. Composition obtains the normalized authority through `JsonlLogStore.logical_path()`
so path identity has one runtime definition instead of duplicate cross-layer imports.

## Append and rotation

Every append enters one `InterprocessFileLock` derived from the stable active-log path.
Inside that critical section the store checks the byte threshold, performs any required
segment rotation, appends one complete UTF-8 JSON line, flushes the file, and preserves
the directory metadata transitions required by the durability layer.

Rotation publishes the active file exactly once to an immutable segment named with a
20-digit monotonically increasing logical generation, for example
`events.jsonl.segment.00000000000000000042.<uuid>`. Generation is derived while holding the
cross-process guard from already durable segment names; wall-clock time, filesystem
`mtime`, inode ordering, and random UUID ordering are never retention authority. The UUID
is uniqueness-only; duplicate logical generations are corruption and fail closed. The
active file is durably renamed first. Only after that publication succeeds may retention
prune generations older than the newest `max_segments`. A crash before publication leaves
the active generation intact; a crash after publication can at worst leave extra old
segments, never require cascade renames or delete the newest durable generation.

Malformed generation names and invalid generation identities fail closed instead of being
silently omitted from evidence queries. This makes the immutable filenames themselves the
durable cross-process ordering contract.

The storage layer owns rotation ordering. Generic fsync/replace primitives remain owned
by the platform durability subsystem; observability does not broaden or reinterpret their
error semantics.

## Query snapshot semantics

Queries freeze **opened segment objects** plus exact byte boundaries while holding the
same writer guard, then release the guard before scanning bytes. They never release the
guard and later reopen a pathname to recover the supposedly frozen generation. POSIX
uses the already-open file descriptor; rename or unlink does not invalidate that object.

Windows opens each frozen object with `FILE_SHARE_READ | FILE_SHARE_WRITE |
FILE_SHARE_DELETE` before the guard is released. Rotation/prune may therefore rename or
unlink the pathname while the reader retains access to the already-open generation. The
reader consumes only the frozen byte prefix and closes every pinned handle afterward.
A genuine pinned-handle I/O failure fails closed; correctness no longer depends on a
bounded pathname-refreeze retry race.

Parsing and filtering remain outside the writer guard, so large queries neither hold the
cross-process mutation lock nor copy unbounded history while that lock is held.

## Regression requirements

Windows and Linux qualification must cover all of the following:

- multiple spawned writers appending and rotating the same log;
- concurrent readers querying while those writers rotate **and prune** retained generations;
- exact preservation of all committed record identities;
- no duplicate records from mixed segment generations;
- stable logical path identity even when a live-leaf `resolve()` would report a renamed
  segment;
- one cross-process guard domain for the active logical log path;
- equal/colliding filesystem mtimes while retention still follows logical generation;
- publication/prune fault injection proving publish-before-prune evidence preservation;
- malformed immutable generation names failing closed.

A retry-only change is not sufficient evidence for correctness. A qualifying fix must
show that the lock/actor identity cannot drift and that every query owns a stable opened
generation object until its frozen prefix has been consumed.

# Server-first development workflow

The Ubuntu validation checkout is the primary implementation and verification
workspace for server-bound research platform work. The local Windows checkout
is a transport and review copy; it is not the source of scientific test
evidence.

## Authority and lifecycle

1. Select a profile-bound server and record its profile digest.
2. Inspect the repository checkout before every mutation. The expected base
   revision must match exactly.
3. Make and verify changes on the server. A dirty workspace may only be
   continued through `scripts/server_repository_develop.py` with an explicit
   `--allow-dirty` decision after the previous operation has been reconciled.
4. Run focused gates first, then the full server suite. A failed mutation is
   reconciled from independent repository evidence before another mutation.
5. Commit on the server with repository-scoped author configuration. Global
   Git configuration and credentials are never written by platform scripts.
6. Export the exact clean server commit with
   `scripts/server_repository_export.py`. The export creates a temporary ref,
   verifies a complete Git bundle, downloads it, and removes the ref and
   sidecar bundle.
7. Import the bundle locally only after server verification, then use the
   existing local GitHub SSH route for the final push when the server has no
   GitHub credential.

This gives one direction of authority:

`server checkout -> server verification -> server commit -> bundle transport -> local GitHub push`

The local checkout must never be used to claim a server experiment passed.

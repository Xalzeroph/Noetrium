# Round 144 — test-package namespace experiment reverted

Date: 2026-08-28

## Candidate change

A temporary working-tree change added 	ests/__init__.py to force project-owned test support imports into an explicit package namespace.

## Reversal

Repository-wide collection showed that the existing test suite intentionally imports several support modules as top-level test helpers. Making the entire test tree a package changed those import semantics and caused collection failures on the Windows controller.

The candidate was therefore reverted rather than forcing hundreds of tests to adopt a repository-local package convention. The final pure-platform tree does **not** contain 	ests/__init__.py.

## Verification

The restored namespace-package layout is covered by the complete upstream regression and release-regression inventories. Test support remains non-production code and is not part of the published
esearch_platform package.

# Linux Container Release Qualification

Noetrium 1.0 qualifies a Linux/amd64 Docker runtime from an immutable, content-addressed source snapshot. Python distributions remain audited inputs to the image, not the production runtime authority.

## Build and qualify

```bash
noetrium dev release build --version 1.0.0
noetrium dev release verify --version 1.0.0
```

For lower-level tooling or CI integration, the same backend is available directly:

```bash
python scripts/release_distribution.py /path/outside/repository
```

The CLI chooses an output directory outside the source tree by default. It computes the source manifest, verifies and materializes the exact platform projection, qualifies wheel/sdist installation, prepares the evidence-bound container context, resolves the concrete Python 3.12 base-image identity, builds the Linux/amd64 image, and runs the container qualification with networking disabled.

The release output includes:

- the qualified Linux/amd64 Docker image archive;
- `CONTAINER_RELEASE_EVIDENCE.json` and container-verification receipt;
- `RELEASE_SHA256SUMS`;
- wheel and source distribution as image-build/SDK artifacts;
- `SHA256SUMS` for the distribution closure;
- SPDX SBOM data;
- wheel and sdist installed-verification receipts;
- runtime-artifact and distribution evidence.

## Runtime contract

The production qualification verifies a Linux/amd64 image built from the exact qualified wheel and exact Python-runtime image identity. It verifies non-root execution, package RECORD integrity, source/wheel/evidence labels, Python 3.12, the `noetrium` console entry point, and the public `NoetriumUnit` / `run` surface by actually starting an isolated container with networking disabled.

Wheel/sdist installation is still checked separately to catch packaging and dependency errors before image construction, but those temporary installation environments are qualification machinery rather than supported production runtimes.

Distribution qualification does not claim that an external model endpoint, GPU, Minecraft server, benchmark dataset, or other provider is live. Those capabilities retain their own provider/runtime qualification boundaries.

## Workspace boundary

`research/`, `benchmarks/`, research-only documentation/workflows, and research-only synchronization scripts are physically removed from the platform source projection before the wheel and sdist are built. Packaging independence is therefore a filesystem property, not merely a setuptools include/exclude convention.

## Strict evidence lane

`python scripts/generate_release_evidence.py` remains available for policies that additionally require architecture and repository-wide regression evidence. Its generated `RELEASE_*` files are derived receipts, not canonical source files.

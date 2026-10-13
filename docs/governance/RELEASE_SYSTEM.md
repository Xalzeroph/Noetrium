# Release System

Noetrium releases are content-addressed. A release binds an exact filesystem source snapshot to the distributions and verification receipts produced from that snapshot. A mutable checkout or a historical green test run is never the release authority.

## Release truth

The canonical maintainer entry is `noetrium dev release`. Noetrium 1.0 is a Linux/amd64, Docker-runtime release: the qualified Linux Docker image is the production runtime authority. The wheel and sdist are intermediate distribution/SDK artifacts used to construct and audit that image; they do not define the production execution environment.

The workflow freezes the current content-addressed source cut, projects out workspace-only research material, qualifies wheel/sdist installation, materializes an evidence-bound container context, builds the Linux image from the exact wheel and Python-runtime image identity, executes container product smoke tests, and emits image/distribution evidence plus checksums and SBOM data.

`RELEASE_MANIFEST.json`, `RELEASE_EVIDENCE.json`, and `RELEASE_AUTHORITY.json` belong to the stricter full-evidence lane driven by `scripts/generate_release_evidence.py`. They are generated artifacts and are intentionally excluded from the canonical source-tree digest. They are not hand-maintained repository state.

## v1 publication sequence

1. Freeze the intended source tree and version metadata.
2. Run repository privacy and boundary scans plus maintained documentation/canonical-generation checks.
3. Build and qualify wheel/sdist from the content-addressed source snapshot as container inputs.
4. Resolve the exact Python 3.12 Linux runtime image identity and build the Noetrium Linux/amd64 Docker image.
5. Run the image with networking disabled and verify non-root execution, package RECORD integrity, `noetrium` CLI, and the `NoetriumUnit` / `run` public surface.
6. Emit the Linux image archive, container release evidence, distribution evidence, SBOM, and SHA-256 checksums.
7. Publish the exact source commit and qualified Linux runtime artifacts under the matching Git tag.

Repository-wide regression evidence may be generated with the full-evidence lane when a release policy requires it. It is separate from the distribution identity itself.

## Commands

Inspect or execute each phase explicitly:

```bash
noetrium dev release status
noetrium dev release prepare --version 1.0.0
noetrium dev release build --version 1.0.0
noetrium dev release verify --version 1.0.0
```

Publish the exact clean source commit, qualified artifacts, tag, and GitHub Release in one workflow:

```bash
noetrium dev release --version 1.0.0 --publish
```

The direct backend remains available for debugging or lower-level integration:

```bash
python scripts/release_distribution.py /path/outside/repository
```

Optional strict evidence lane:

```bash
python scripts/generate_release_evidence.py
python scripts/verify_release_evidence.py
```

## Repository boundary

The upstream source contains reusable platform code, generic providers, maintained tests, examples, documentation, and release tooling. Formal Python distributions physically exclude the research workspace, benchmark workspace, research-only workflows, and research-only synchronization scripts. Private projects, unpublished experiment state, machine inventories, credentials, local paths, run outputs, and project-specific evidence are not release content.

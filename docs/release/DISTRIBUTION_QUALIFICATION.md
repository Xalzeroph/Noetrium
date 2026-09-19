# Distribution qualification

A source-tree test pass is not sufficient release evidence. Formal Python distribution qualification uses:

```bash
python scripts/release_distribution.py <output-directory-outside-repository>
```

The command fails unless the Git worktree is clean. It materializes one exact source root directly from raw Git object-database bytes using `git ls-tree` plus `git cat-file --batch`, builds the governance release manifest and both Python distributions from that same immutable cut, and re-checks HEAD/branch/clean state before publishing claim-grade evidence. A clean checkout that changes HEAD during qualification is rejected rather than silently pairing another source tree with the original SHA. Git archive/export attributes are never consulted, so `export-ignore` cannot omit tracked files and `export-subst` cannot rewrite tracked blob bytes in the formal build input.

Each installed artifact must:

- import the public `noetrium` package from the isolated environment's `site-packages`;
- expose the installed `noetrium` console script;
- execute the historical Operator smoke lifecycle `run -> inspect -> stop -> resume -> reconcile -> evidence` successfully;
- preserve that synthetic smoke state across command processes.

These installed-artifact checks qualify packaging, console-script wiring, isolation and the legacy Operator smoke fixture only. Their machine receipts explicitly carry `qualification_scope=operator-smoke-only` and `npe_verified=false`; they are not Section-37 New Project Experience evidence.

The formal output includes wheel/sdist artifacts, installed-verification receipts, `SBOM.spdx.json`, `SHA256SUMS`, `DISTRIBUTION_RELEASE_EVIDENCE.json`, and a digest for the evidence document.

The evidence document binds source SHA, branch, release-manifest digest, source-tree SHA-256, Python/package versions, build-command output digests, artifact sizes/checksums, SBOM checksum and installed-verification receipt checksums.

## Container qualification

The release container is distribution-bound rather than rebuilt from checkout source. CI first qualifies wheel/sdist, then prepares an exact container context from the already verified wheel and immutable Git blobs for the Dockerfile/entrypoint:

```bash
python scripts/prepare_container_context.py <distribution-dir> <context-dir> \
  --expected-source-sha "$GIT_SHA"
docker build \
  --build-arg PLATFORM_SOURCE_SHA="$GIT_SHA" \
  --build-arg PLATFORM_WHEEL_SHA256="$WHEEL_SHA256" \
  --build-arg PLATFORM_DISTRIBUTION_EVIDENCE_SHA256="$DISTRIBUTION_EVIDENCE_SHA256" \
  -t "noetrium:$GIT_SHA" <context-dir>
python scripts/verify_container_image.py "noetrium:$GIT_SHA" \
  --expected-source-sha "$GIT_SHA" \
  --expected-wheel-sha256 "$WHEEL_SHA256" \
  --expected-distribution-evidence-sha256 "$DISTRIBUTION_EVIDENCE_SHA256" \
  --output container-verification.json
```

The image embeds that exact wheel as a read-only provenance artifact. Build-time verification rejects a wheel whose bytes do not match the authority digest. Runtime verification independently checks the revision/wheel/distribution-evidence labels, recomputes the embedded wheel SHA-256, verifies every hashed installed file against the wheel `RECORD`, attests effective UID/GID (not only Docker `Config.User`), requires both to be non-root, and then executes the full historical Operator smoke lifecycle with networking disabled. The container receipt likewise records `npe_verified=false`; this smoke does not satisfy the Section-37 project/reference acceptance contract. The receipt binds the image ID/digest to the exact wheel and distribution evidence.

Changing mutable checkout Platform source after wheel qualification cannot alter the image code because no `noetrium_platform/**` source tree enters the container build context. Modified installed `site-packages`, a forged wheel label, a stale distribution receipt, or effective root execution all fail closed.

The container test does not create domain evidence. Minecraft/model/live qualification remains with the owning Roles and their explicitly allocated server windows.

## Product assurance gate

CI first runs:

```bash
python scripts/product_assurance_gate.py --full --output product-assurance.json
```

This emits one machine-readable receipt and exits nonzero on the first blocking failure. The full gate verifies the L0-L8 taxonomy assignment, the required provider-conformance matrix, the architecture gate and the complete pytest regression. The receipt records repository, branch, exact HEAD SHA, release source-tree SHA-256 and clean state at both opening and closing source-identity checks. A clean HEAD/branch/tree drift during the gate makes the receipt non-passing even when every child command itself returned zero.

Provider conformance is declared in `tests/PROVIDER_CONFORMANCE.json`. The matrix must contain exactly the durable, environment, model, effect and checkpoint classes and points to first-party behavior/recovery tests that are themselves classified exactly once by `tests/TEST_SYSTEM.json`.

Resource shared-carrier fencing tests are L5 `concurrency-capacity` evidence. New cross-role resource fencing tests must extend that existing taxonomy rule and remain classified exactly once rather than creating a parallel family.

The GitHub workflow runs source-bound product assurance, wheel/sdist qualification, exact-SHA container build/verification, and uploads all receipts for the exact CI source revision.

## Licensing boundary

Project ownership selected Apache License 2.0. Formal releases therefore require PEP 639 `License-Expression: Apache-2.0`, `License-File` entries for `LICENSE`, `NOTICE`, and `THIRD_PARTY_NOTICES.md`, and those exact legal files in both wheel and sdist. `release_distribution.py` verifies these conditions before publishing evidence; the v4 distribution receipt records the verified OSS metadata digests and legal-file authority. The project package is declared `Apache-2.0` in the SBOM, while bundled or external third-party components retain their own upstream licenses and are not relicensed by this declaration.

The container image installs only the already-qualified formal wheel; it does not rebuild Platform code from a mutable checkout. Container qualification verifies wheel/RECORD integrity, effective non-root UID/GID, doctor, and the full reference lifecycle with networking disabled.

## Section-37 NPE clean-room gate

New Project Experience qualification is a separate, stricter authority from the historical Operator smoke above:

```bash
python scripts/verify_npe_cleanroom.py <qualified-wheel-or-sdist> \
  --output npe-clean-room.json
```

The verifier creates a fresh virtual environment and workspace, removes ambient `PYTHONPATH/PYTHONHOME`, installs only the supplied artifact, and proves `noetrium` resolves inside that verification environment. It then runs the installed `noetrium project create`, `project doctor`, and generated `project test` surfaces. `project test` itself builds and installs the generated downstream package into an isolated temporary install root before executing its contract suite, so checkout/src-only import success cannot satisfy NPE. Machine JSON is parsed from the complete command output; bounded stdout/stderr tails remain diagnostic-only and are never the authority for NPE state. Public-import-boundary readiness is taken from the typed doctor receipt.

The receipt schema is `noetrium.npe-clean-room.v2` and records the generated template profile. `npe_verified` is true only when the complete installed author flow passes: public Method Host readiness, generated project test, public-import boundary, an explicit downstream-owned typed `RunControlPort` binding, six revision-fenced lifecycle actions, finalized evidence and a fresh-process reopen. The default installed-artifact path must be `template_profile=author`; it may not fall back to provider-first scaffolding.

The verifier materializes its deterministic lifecycle binding inside the clean downstream project. That binding imports only public `noetrium` contracts plus the standard library, stores state at an explicit run-local path with atomic replacement, emits typed receipts and evidence references, and is executed in separate processes. It does not create an Operator-side compiler or a duplicate Platform authority. Missing, malformed, stale or non-finalized receipts remain fail-closed. The historical `noetrium_platform.product.operator.reference` smoke is excluded from NPE evidence.

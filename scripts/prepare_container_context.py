from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RUNTIME_ARTIFACT_SCHEMA = "noetrium.runtime-artifact.v1"
_RUNTIME_ARTIFACT_EVIDENCE = "RUNTIME_ARTIFACT_EVIDENCE.json"


@dataclass(frozen=True, slots=True)
class ContainerContextReceipt:
    schema: str
    source_sha: str
    source_tree_sha256: str
    distribution_evidence_sha256: str
    wheel_sha256: str
    wheel_size: int
    dockerfile_sha256: str
    entrypoint_sha256: str
    runtime_dependencies_sha256: str


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())

def _load_runtime_artifact_evidence(path: Path, *, expected_source_sha: str) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("distribution evidence is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("distribution evidence must be a JSON object")
    if payload.get("schema") != _RUNTIME_ARTIFACT_SCHEMA:
        raise ValueError("runtime artifact evidence schema is not current")
    if payload.get("source_sha") != expected_source_sha:
        raise ValueError("runtime artifact evidence source SHA mismatch")
    if payload.get("manifest_source") != "content-addressed-filesystem-snapshot":
        raise ValueError("runtime artifact manifest is not bound to content-addressed source snapshot")
    manifest_digest = payload.get("release_manifest_digest")
    if not isinstance(manifest_digest, str) or not _SHA256_RE.fullmatch(manifest_digest):
        raise ValueError("runtime artifact release-manifest digest is invalid")
    build_command = payload.get("build_command")
    if not isinstance(build_command, dict) or build_command.get("source_sha") != expected_source_sha:
        raise ValueError("runtime artifact build source identity is invalid")
    if build_command.get("cwd_mode") != "external-content-addressed-snapshot":
        raise ValueError("runtime artifact build did not use isolated content-addressed source")
    if build_command.get("source_materialization_schema") != "noetrium.filesystem-source-snapshot.v1":
        raise ValueError("runtime artifact source materialization schema is invalid")
    materialization_digest = build_command.get("source_materialization_sha256")
    if not isinstance(materialization_digest, str) or not _SHA256_RE.fullmatch(materialization_digest):
        raise ValueError("runtime artifact source-materialization digest is invalid")
    file_count = build_command.get("source_materialization_file_count")
    if type(file_count) is not int or file_count < 1:
        raise ValueError("runtime artifact source-materialization file count is invalid")
    tree_digest = payload.get("source_tree_sha256")
    if not isinstance(tree_digest, str) or not _SHA256_RE.fullmatch(tree_digest):
        raise ValueError("runtime artifact evidence source-tree digest is invalid")
    return payload, raw

def prepare_container_context(
    distribution_dir: Path,
    output: Path,
    *,
    expected_source_sha: str,
) -> ContainerContextReceipt:
    source_sha = expected_source_sha.strip().lower()
    if not _SHA256_RE.fullmatch(source_sha):
        raise ValueError("expected source SHA must be a lowercase SHA-256 source-tree digest")
    distribution_dir = Path(distribution_dir).resolve()
    evidence_path = distribution_dir / _RUNTIME_ARTIFACT_EVIDENCE
    evidence, evidence_raw = _load_runtime_artifact_evidence(
        evidence_path, expected_source_sha=source_sha
    )
    evidence_digest = _sha256_bytes(evidence_raw)
    sidecar = distribution_dir / f"{_RUNTIME_ARTIFACT_EVIDENCE}.sha256"
    if not sidecar.is_file():
        raise ValueError("runtime artifact evidence digest sidecar is missing")
    expected_sidecar = f"{evidence_digest}  {evidence_path.name}\n".encode("utf-8")
    if sidecar.read_bytes() != expected_sidecar:
        raise ValueError("runtime artifact evidence digest sidecar mismatch")
    oss_metadata = evidence.get("oss_metadata")
    if not isinstance(oss_metadata, dict):
        raise ValueError("runtime artifact OSS metadata authority is missing")
    if oss_metadata.get("license_expression") != "Apache-2.0":
        raise ValueError("runtime artifact OSS license expression is invalid")
    license_files = oss_metadata.get("license_files")
    if license_files != ["LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"]:
        raise ValueError("runtime artifact OSS license-file authority is invalid")
    artifacts = evidence.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("runtime artifact authority is missing")
    wheel_names = [name for name in artifacts if isinstance(name, str) and name.endswith(".whl")]
    if len(wheel_names) != 1:
        raise ValueError("runtime artifact evidence must bind exactly one wheel")
    wheel_name = wheel_names[0]
    wheel_authority = artifacts[wheel_name]
    if not isinstance(wheel_authority, dict):
        raise ValueError("runtime artifact wheel authority is invalid")
    expected_wheel_sha = wheel_authority.get("sha256")
    if not isinstance(expected_wheel_sha, str) or not _SHA256_RE.fullmatch(expected_wheel_sha):
        raise ValueError("runtime artifact wheel SHA256 is invalid")
    wheel = distribution_dir / wheel_name
    expected_wheel_size = wheel_authority.get("size")
    if type(expected_wheel_size) is not int or expected_wheel_size < 1:
        raise ValueError("runtime artifact wheel size authority is invalid")
    if (
        not wheel.is_file()
        or wheel.stat().st_size != expected_wheel_size
        or _sha256(wheel) != expected_wheel_sha
    ):
        raise ValueError("runtime artifact wheel bytes do not match evidence authority")
    tree_digest = evidence["source_tree_sha256"]
    if not isinstance(tree_digest, str):
        raise ValueError("runtime artifact source-tree digest is invalid")
    build_assets = evidence.get("container_build_assets")
    if not isinstance(build_assets, dict):
        raise ValueError("runtime artifact container-build asset authority is missing")

    def bound_asset(name: str) -> bytes:
        row = build_assets.get(name)
        if not isinstance(row, dict):
            raise ValueError(f"runtime artifact container-build asset is missing: {name}")
        relative = row.get("path")
        digest = row.get("sha256")
        size = row.get("size")
        if (
            not isinstance(relative, str)
            or relative.startswith("/")
            or ".." in Path(relative).parts
            or not isinstance(digest, str)
            or not _SHA256_RE.fullmatch(digest)
            or type(size) is not int
            or size < 1
        ):
            raise ValueError(f"runtime artifact container-build asset authority is invalid: {name}")
        path = distribution_dir / relative
        if not path.is_file():
            raise ValueError(f"runtime artifact container-build asset bytes are missing: {name}")
        raw = path.read_bytes()
        if len(raw) != size or _sha256_bytes(raw) != digest:
            raise ValueError(f"runtime artifact container-build asset bytes drifted: {name}")
        return raw

    dockerfile_raw = bound_asset("dockerfile")
    entrypoint_raw = bound_asset("entrypoint")
    runtime_dependencies_raw = bound_asset("runtime_dependencies")

    output = Path(output).resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    shutil.copyfile(wheel, output / wheel.name)
    (output / "Dockerfile").write_bytes(dockerfile_raw)
    (output / "container-entrypoint.sh").write_bytes(entrypoint_raw)
    (output / "runtime-dependencies.txt").write_bytes(runtime_dependencies_raw)
    receipt = ContainerContextReceipt(
        schema="noetrium.container-build-context.v2",
        source_sha=source_sha,
        source_tree_sha256=tree_digest,
        distribution_evidence_sha256=evidence_digest,
        wheel_sha256=expected_wheel_sha,
        wheel_size=wheel.stat().st_size,
        dockerfile_sha256=_sha256_bytes(dockerfile_raw),
        entrypoint_sha256=_sha256_bytes(entrypoint_raw),
        runtime_dependencies_sha256=_sha256_bytes(runtime_dependencies_raw),
    )
    (output / "CONTAINER_CONTEXT.json").write_text(
        json.dumps(asdict(receipt), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return receipt

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("distribution_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--expected-source-sha", required=True)
    args = parser.parse_args(argv)
    try:
        receipt = prepare_container_context(
            args.distribution_dir,
            args.output,
            expected_source_sha=args.expected_source_sha,
        )
    except Exception as exc:
        print(f"CONTAINER_CONTEXT_FAIL {type(exc).__qualname__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(asdict(receipt), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

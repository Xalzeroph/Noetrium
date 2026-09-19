from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DISTRIBUTION_SCHEMA = "noetrium.distribution-release.v4"


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


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())

def _git_blob(source_sha: str, path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{source_sha}:{path}"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(message or f"missing exact-source build asset: {path}")
    return completed.stdout


def _load_distribution_evidence(path: Path, *, expected_source_sha: str) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("distribution evidence is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("distribution evidence must be a JSON object")
    if payload.get("schema") != _DISTRIBUTION_SCHEMA:
        raise ValueError("distribution evidence schema is not current")
    if payload.get("source_sha") != expected_source_sha:
        raise ValueError("distribution evidence source SHA mismatch")
    if payload.get("manifest_source") != "external-git-object-database":
        raise ValueError("distribution manifest is not bound to raw Git object source")
    manifest_digest = payload.get("release_manifest_digest")
    if not isinstance(manifest_digest, str) or not _SHA256_RE.fullmatch(manifest_digest):
        raise ValueError("distribution release-manifest digest is invalid")
    build_command = payload.get("build_command")
    if not isinstance(build_command, dict) or build_command.get("source_sha") != expected_source_sha:
        raise ValueError("distribution build source identity is invalid")
    if build_command.get("cwd_mode") != "external-git-object-database":
        raise ValueError("distribution build did not use raw Git object source")
    if build_command.get("source_materialization_schema") != "noetrium.git-object-materialization.v1":
        raise ValueError("distribution source materialization schema is invalid")
    materialization_digest = build_command.get("source_materialization_sha256")
    if not isinstance(materialization_digest, str) or not _SHA256_RE.fullmatch(materialization_digest):
        raise ValueError("distribution source-materialization digest is invalid")
    file_count = build_command.get("source_materialization_file_count")
    if type(file_count) is not int or file_count < 1:
        raise ValueError("distribution source-materialization file count is invalid")
    tree_digest = payload.get("source_tree_sha256")
    if not isinstance(tree_digest, str) or not _SHA256_RE.fullmatch(tree_digest):
        raise ValueError("distribution evidence source-tree digest is invalid")
    return payload, raw

def prepare_container_context(
    distribution_dir: Path,
    output: Path,
    *,
    expected_source_sha: str,
) -> ContainerContextReceipt:
    source_sha = expected_source_sha.strip().lower()
    if not _SHA40_RE.fullmatch(source_sha):
        raise ValueError("expected source SHA must be a lowercase 40-character Git SHA")
    distribution_dir = Path(distribution_dir).resolve()
    evidence_path = distribution_dir / "DISTRIBUTION_RELEASE_EVIDENCE.json"
    evidence, evidence_raw = _load_distribution_evidence(
        evidence_path, expected_source_sha=source_sha
    )
    evidence_digest = _sha256_bytes(evidence_raw)
    sidecar = distribution_dir / "DISTRIBUTION_RELEASE_EVIDENCE.json.sha256"
    if not sidecar.is_file():
        raise ValueError("distribution evidence digest sidecar is missing")
    expected_sidecar = f"{evidence_digest}  {evidence_path.name}\n".encode("utf-8")
    if sidecar.read_bytes() != expected_sidecar:
        raise ValueError("distribution evidence digest sidecar mismatch")
    oss_metadata = evidence.get("oss_metadata")
    if not isinstance(oss_metadata, dict):
        raise ValueError("distribution OSS metadata authority is missing")
    if oss_metadata.get("license_expression") != "Apache-2.0":
        raise ValueError("distribution OSS license expression is invalid")
    license_files = oss_metadata.get("license_files")
    if license_files != ["LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"]:
        raise ValueError("distribution OSS license-file authority is invalid")
    artifacts = evidence.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("distribution artifact authority is missing")
    wheel_names = [name for name in artifacts if isinstance(name, str) and name.endswith(".whl")]
    if len(wheel_names) != 1:
        raise ValueError("distribution evidence must bind exactly one wheel")
    wheel_name = wheel_names[0]
    wheel_authority = artifacts[wheel_name]
    if not isinstance(wheel_authority, dict):
        raise ValueError("distribution wheel authority is invalid")
    expected_wheel_sha = wheel_authority.get("sha256")
    if not isinstance(expected_wheel_sha, str) or not _SHA256_RE.fullmatch(expected_wheel_sha):
        raise ValueError("distribution wheel SHA256 is invalid")
    wheel = distribution_dir / wheel_name
    expected_wheel_size = wheel_authority.get("size")
    if type(expected_wheel_size) is not int or expected_wheel_size < 1:
        raise ValueError("distribution wheel size authority is invalid")
    if (
        not wheel.is_file()
        or wheel.stat().st_size != expected_wheel_size
        or _sha256(wheel) != expected_wheel_sha
    ):
        raise ValueError("distribution wheel bytes do not match evidence authority")
    tree_digest = evidence["source_tree_sha256"]
    if not isinstance(tree_digest, str):
        raise ValueError("distribution source-tree digest is invalid")
    dockerfile_raw = _git_blob(source_sha, "deploy/Dockerfile")
    entrypoint_raw = _git_blob(source_sha, "deploy/container-entrypoint.sh")

    output = Path(output).resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    shutil.copyfile(wheel, output / wheel.name)
    (output / "Dockerfile").write_bytes(dockerfile_raw)
    (output / "container-entrypoint.sh").write_bytes(entrypoint_raw)
    receipt = ContainerContextReceipt(
        schema="noetrium.container-build-context.v1",
        source_sha=source_sha,
        source_tree_sha256=tree_digest,
        distribution_evidence_sha256=evidence_digest,
        wheel_sha256=expected_wheel_sha,
        wheel_size=wheel.stat().st_size,
        dockerfile_sha256=_sha256_bytes(dockerfile_raw),
        entrypoint_sha256=_sha256_bytes(entrypoint_raw),
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

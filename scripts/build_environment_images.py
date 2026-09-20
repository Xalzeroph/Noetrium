from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "deploy" / "environments" / "catalog.json"


def _run(
    argv: Iterable[str],
    *,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    capture: bool = False,
) -> str:
    completed = subprocess.run(
        tuple(argv),
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=False,
    )
    if completed.returncode != 0:
        if capture:
            sys.stderr.write(completed.stdout or "")
            sys.stderr.write(completed.stderr or "")
        raise RuntimeError(
            f"command failed rc={completed.returncode}: {' '.join(argv)}"
        )
    return (completed.stdout or "").strip() if capture else ""


def _git(*args: str) -> str:
    return _run(("git", *args), capture=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_catalog() -> dict:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if data.get("schema") != "noetrium.environment-container-profiles.v1":
        raise RuntimeError("environment profile catalog schema is not current")
    return data


def _profile_map(data: dict) -> dict[str, dict]:
    rows = data.get("profiles")
    if not isinstance(rows, list):
        raise RuntimeError("environment profile catalog profiles must be a list")
    result: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("environment profile row must be an object")
        profile_id = row.get("profile_id")
        if not isinstance(profile_id, str) or not profile_id:
            raise RuntimeError("environment profile id must be non-empty")
        result[profile_id] = row
    return result


def _image_exists(tag: str) -> bool:
    completed = subprocess.run(
        ("docker", "image", "inspect", tag),
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


def _image_identity(tag: str) -> dict:
    raw = _run(
        (
            "docker",
            "image",
            "inspect",
            tag,
            "--format",
            "{{json .}}",
        ),
        capture=True,
    )
    data = json.loads(raw)
    return {
        "tag": tag,
        "id": data.get("Id"),
        "repo_digests": data.get("RepoDigests") or [],
        "created": data.get("Created"),
        "labels": (data.get("Config") or {}).get("Labels") or {},
    }


def build_environment_images(
    *,
    profiles: tuple[str, ...],
    work_root: Path,
    output: Path,
    java_runtime_image: str,
    node_version: str,
    rebuild: bool = False,
) -> dict:
    source_sha = _git("rev-parse", "HEAD")
    if _git("status", "--porcelain"):
        raise RuntimeError("environment image build requires a clean checkout")

    branch = _git("branch", "--show-current")
    catalog = _load_catalog()
    by_id = _profile_map(catalog)
    unknown = tuple(sorted(set(profiles) - set(by_id)))
    if unknown:
        raise RuntimeError(f"unknown environment profiles: {unknown!r}")
    base_only = tuple(
        profile_id
        for profile_id in profiles
        if by_id[profile_id].get("build_mode") == "base-only"
    )
    if base_only:
        raise RuntimeError(
            f"base-only profiles do not build an image: {base_only!r}"
        )

    _run((sys.executable, "scripts/environment_profiles.py", "validate"))
    _run(("docker", "--version"))
    _run(("docker", "compose", "version"))

    work_root = work_root.resolve()
    if work_root.exists():
        shutil.rmtree(work_root)
    distribution = work_root / "distribution"
    context = work_root / "container-context"
    tooling_venv = work_root / "tooling-venv"
    runtime_root = work_root / "runtime"
    work_root.mkdir(parents=True)
    for state_dir in (
        runtime_root / "platform-state",
        runtime_root / "minecraft",
    ):
        state_dir.mkdir(parents=True, exist_ok=True)
        state_dir.chmod(0o777)

    _run((sys.executable, "-m", "venv", str(tooling_venv)))
    tool_python = (
        tooling_venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    _run(
        (
            str(tool_python),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "pip",
            "build>=1.2,<2",
        )
    )

    _run(
        (
            str(tool_python),
            "scripts/release_distribution.py",
            str(distribution),
        )
    )
    _run(
        (
            str(tool_python),
            "scripts/prepare_container_context.py",
            str(distribution),
            str(context),
            "--expected-source-sha",
            source_sha,
        )
    )
    context_receipt = json.loads(
        (context / "CONTAINER_CONTEXT.json").read_text(encoding="utf-8")
    )
    wheel_sha256 = context_receipt["wheel_sha256"]
    distribution_evidence_sha256 = context_receipt[
        "distribution_evidence_sha256"
    ]

    base_tag = f"noetrium:{source_sha}"
    reused_base = _image_exists(base_tag) and not rebuild
    if not reused_base:
        _run(
            (
                "docker",
                "build",
                "--build-arg",
                f"PLATFORM_SOURCE_SHA={source_sha}",
                "--build-arg",
                f"PLATFORM_WHEEL_SHA256={wheel_sha256}",
                "--build-arg",
                (
                    "PLATFORM_DISTRIBUTION_EVIDENCE_SHA256="
                    f"{distribution_evidence_sha256}"
                ),
                "--tag",
                base_tag,
                str(context),
            )
        )
    base_verification = work_root / "base-container-verification.json"
    _run(
        (
            str(tool_python),
            "scripts/verify_container_image.py",
            base_tag,
            "--expected-source-sha",
            source_sha,
            "--expected-wheel-sha256",
            wheel_sha256,
            "--expected-distribution-evidence-sha256",
            distribution_evidence_sha256,
            "--output",
            str(base_verification),
        )
    )

    base_identity = _image_identity(base_tag)
    base_identity["reused"] = reused_base
    images: dict[str, dict] = {"base": base_identity}
    for profile_id in profiles:
        row = by_id[profile_id]
        compose = row.get("compose")
        image_env = row.get("image_env")
        if not isinstance(compose, str) or not compose:
            raise RuntimeError(f"{profile_id}: compose path missing")
        if not isinstance(image_env, str) or not image_env:
            raise RuntimeError(f"{profile_id}: image_env missing")
        tag = f"noetrium-env-{profile_id}:{source_sha}"
        env = os.environ.copy()
        env["PLATFORM_IMAGE"] = base_tag
        env[image_env] = tag
        env["JAVA_RUNTIME_IMAGE"] = java_runtime_image
        env["NODE_VERSION"] = node_version
        env["PLATFORM_HOST_DATA_ROOT"] = str(runtime_root)
        reused_profile = _image_exists(tag) and not rebuild
        if not reused_profile:
            _run(
                (
                    "docker",
                    "compose",
                    "-f",
                    "deploy/compose.yaml",
                    "-f",
                    compose,
                    "build",
                    "platform-runtime",
                ),
                env=env,
            )
        _run(
            (
                "docker",
                "compose",
                "-f",
                "deploy/compose.yaml",
                "-f",
                compose,
                "run",
                "--rm",
                "platform-runtime",
                "environment-doctor",
                profile_id,
            ),
            env=env,
        )
        profile_identity = _image_identity(tag)
        profile_identity["reused"] = reused_profile
        images[profile_id] = profile_identity

    receipt = {
        "schema": "noetrium.environment-image-build.v1",
        "source_sha": source_sha,
        "branch": branch,
        "catalog_sha256": _sha256(CATALOG_PATH),
        "wheel_sha256": wheel_sha256,
        "distribution_evidence_sha256": distribution_evidence_sha256,
        "java_runtime_image": java_runtime_image,
        "node_version": node_version,
        "profiles": list(profiles),
        "rebuild": rebuild,
        "images": images,
        "base_verification": json.loads(
            base_verification.read_text(encoding="utf-8")
        ),
    }
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profiles",
        nargs="+",
        default=["minecraft", "embodied", "gui", "web", "software"],
    )
    parser.add_argument(
        "--work-root",
        type=Path,
        default=Path(tempfile.gettempdir()) / "noetrium-environment-images",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("environment-image-build.json"),
    )
    parser.add_argument(
        "--java-runtime-image",
        default=os.environ.get(
            "JAVA_RUNTIME_IMAGE", "eclipse-temurin:21-jre-jammy"
        ),
    )
    parser.add_argument(
        "--node-version",
        default=os.environ.get("NODE_VERSION", "22.22.2"),
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Ignore exact-SHA image cache and rebuild base/profile images.",
    )
    args = parser.parse_args(argv)
    try:
        build_environment_images(
            profiles=tuple(args.profiles),
            work_root=args.work_root,
            output=args.output,
            java_runtime_image=args.java_runtime_image,
            node_version=args.node_version,
            rebuild=args.rebuild,
        )
    except Exception as exc:
        print(
            f"ENVIRONMENT_IMAGE_BUILD_FAIL {type(exc).__qualname__}: {exc}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

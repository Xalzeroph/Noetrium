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
EXPECTED_PROFILES = frozenset({"minecraft", "embodied", "gui", "web", "software", "text_world"})
FORBIDDEN_IMAGE_MARKERS = (
    "copy research",
    "copy benchmarks",
    "copy datasets",
    "copy checkpoints",
    "copy experiments",
)
WHEEL_LABEL = "org.opencontainers.image.noetrium.wheel.sha256"
DISTRIBUTION_LABEL = "org.opencontainers.image.noetrium.distribution-evidence.sha256"
REVISION_LABEL = "org.opencontainers.image.revision"
PYTHON_RUNTIME_CANONICAL_IMAGE = "python:3.12-slim-bookworm"
JAVA_RUNTIME_CANONICAL_IMAGE = "eclipse-temurin:21-jre-jammy"


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


def validate_catalog(data: dict, profiles: dict[str, dict]) -> dict:
    errors: list[str] = []
    if set(profiles) != EXPECTED_PROFILES:
        errors.append(
            "profile set drift: "
            f"expected={sorted(EXPECTED_PROFILES)!r} observed={sorted(profiles)!r}"
        )

    base = data.get("base")
    if not isinstance(base, dict):
        errors.append("base image authority must be an object")
    else:
        if base.get("build_mode") != "evidence-bound-wheel":
            errors.append("base image must remain evidence-bound-wheel")
        for field in ("dockerfile", "compose"):
            value = base.get(field)
            if not isinstance(value, str) or not value:
                errors.append(f"base {field} must be non-empty")
            elif not (ROOT / value).is_file():
                errors.append(f"base {field} does not exist: {value}")

    for profile_id, row in sorted(profiles.items()):
        if row.get("category_id") != profile_id:
            errors.append(f"{profile_id}: category_id must match canonical environment category")
        if row.get("extends") != "base":
            errors.append(f"{profile_id}: environment profile must extend base")
        if profile_id == "text_world":
            if row.get("build_mode") != "base-only":
                errors.append("text_world must remain base-only")
            continue

        dockerfile_text = ""
        compose_text = ""
        for field in ("dockerfile", "compose"):
            value = row.get(field)
            if not isinstance(value, str) or not value:
                errors.append(f"{profile_id}: {field} must be non-empty")
                continue
            path = ROOT / value
            if not path.is_file():
                errors.append(f"{profile_id}: missing {field}: {value}")
                continue
            if field == "dockerfile":
                dockerfile_text = path.read_text(encoding="utf-8")
            else:
                compose_text = path.read_text(encoding="utf-8")

        if dockerfile_text:
            lowered = dockerfile_text.lower()
            if "arg platform_base_image" not in lowered:
                errors.append(f"{profile_id}: Dockerfile must declare PLATFORM_BASE_IMAGE")
            if "from ${platform_base_image}" not in lowered:
                errors.append(f"{profile_id}: Dockerfile must consume PLATFORM_BASE_IMAGE")
            for marker in FORBIDDEN_IMAGE_MARKERS:
                if marker in lowered:
                    errors.append(f"{profile_id}: downstream/scientific marker leaked into image: {marker}")
        if compose_text:
            if "environment-doctor" not in compose_text:
                errors.append(f"{profile_id}: compose overlay lacks environment doctor")
            if profile_id not in compose_text:
                errors.append(f"{profile_id}: compose overlay lacks profile identity")

    if errors:
        raise RuntimeError("; ".join(errors))
    return {
        "schema": "noetrium.environment-profile-validation.v1",
        "status": "pass",
        "profile_count": len(profiles),
        "image_profile_count": sum(
            1 for row in profiles.values() if row.get("build_mode") != "base-only"
        ),
        "base_build_mode": data["base"]["build_mode"],
    }


def _digest_label(labels: dict, key: str) -> str:
    value = labels.get(key)
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise RuntimeError(f"cached base image has invalid provenance label: {key}")
    return value


def _cached_base_provenance(identity: dict, source_sha: str) -> tuple[str, str]:
    labels = identity.get("labels")
    if not isinstance(labels, dict):
        raise RuntimeError("cached base image labels are invalid")
    if labels.get(REVISION_LABEL) != source_sha:
        raise RuntimeError("cached base image source revision does not match checkout")
    return _digest_label(labels, WHEEL_LABEL), _digest_label(labels, DISTRIBUTION_LABEL)


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
    python_runtime_image: str,
    python_runtime_canonical_image: str,
    java_runtime_image: str,
    java_runtime_canonical_image: str,
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
    validate_catalog(catalog, by_id)

    _run(("docker", "--version"))
    _run(("docker", "compose", "version"))

    work_root = work_root.resolve()
    scratch_root = work_root / "build"
    runtime_root = work_root / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    for state_name in ("platform-state", *profiles):
        state_dir = runtime_root / state_name
        state_dir.mkdir(parents=True, exist_ok=True)
        state_dir.chmod(0o777)

    base_tag = f"noetrium:{source_sha}"
    reused_base = _image_exists(base_tag) and not rebuild
    build_mode = "reused-verified-base" if reused_base else "qualified-distribution-build"

    if reused_base:
        scratch_root.mkdir(parents=True, exist_ok=True)
        base_identity = _image_identity(base_tag)
        wheel_sha256, distribution_evidence_sha256 = _cached_base_provenance(
            base_identity, source_sha
        )
    else:
        if scratch_root.exists():
            shutil.rmtree(scratch_root)
        distribution = scratch_root / "distribution"
        context = scratch_root / "container-context"
        tooling_venv = scratch_root / "tooling-venv"
        scratch_root.mkdir(parents=True, exist_ok=True)

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
        _run(
            (
                "docker",
                "build",
                "--build-arg",
                f"PYTHON_RUNTIME_IMAGE={python_runtime_image}",
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
        base_identity = _image_identity(base_tag)

    base_verification = scratch_root / "base-container-verification.json"
    _run(
        (
            sys.executable,
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

    base_identity["reused"] = reused_base
    images: dict[str, dict] = {"base": base_identity}
    for profile_id in profiles:
        row = by_id[profile_id]
        if row.get("build_mode") == "base-only":
            _run(
                (
                    "docker",
                    "run",
                    "--rm",
                    base_tag,
                    "environment-doctor",
                    profile_id,
                )
            )
            profile_identity = dict(base_identity)
            profile_identity["profile_id"] = profile_id
            profile_identity["base_only"] = True
            profile_identity["reused"] = True
            images[profile_id] = profile_identity
            continue

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
        "runtime_image_sources": {
            "python": {
                "canonical_image": python_runtime_canonical_image,
                "source_image": python_runtime_image,
                "source_identity": (
                    _image_identity(python_runtime_image)
                    if _image_exists(python_runtime_image)
                    else None
                ),
            },
            "java": {
                "canonical_image": java_runtime_canonical_image,
                "source_image": java_runtime_image,
                "source_identity": (
                    _image_identity(java_runtime_image)
                    if "minecraft" in profiles and _image_exists(java_runtime_image)
                    else None
                ),
            },
        },
        "node_version": node_version,
        "profiles": list(profiles),
        "rebuild": rebuild,
        "build_mode": build_mode,
        "runtime_root": str(runtime_root),
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


def _print_json(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Canonical environment-profile and image-build entrypoint."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list reusable environment profiles")
    sub.add_parser("validate", help="validate the environment-profile authority")
    show = sub.add_parser("show", help="show one environment profile")
    show.add_argument("profile_id")

    build = sub.add_parser("build", help="build or reuse exact-SHA environment images")
    build.add_argument(
        "--profiles",
        nargs="+",
        default=sorted(EXPECTED_PROFILES),
    )
    build.add_argument(
        "--work-root",
        type=Path,
        default=Path(tempfile.gettempdir()) / "noetrium-environment-images",
    )
    build.add_argument(
        "--output",
        type=Path,
        default=Path("environment-image-build.json"),
    )
    build.add_argument(
        "--python-runtime-canonical-image",
        default=os.environ.get(
            "PYTHON_RUNTIME_CANONICAL_IMAGE", PYTHON_RUNTIME_CANONICAL_IMAGE
        ),
    )
    build.add_argument(
        "--python-runtime-image",
        default=os.environ.get(
            "PYTHON_RUNTIME_IMAGE", PYTHON_RUNTIME_CANONICAL_IMAGE
        ),
        help="Actual Python runtime source image; may use a deployment registry mirror.",
    )
    build.add_argument(
        "--java-runtime-canonical-image",
        default=os.environ.get(
            "JAVA_RUNTIME_CANONICAL_IMAGE", JAVA_RUNTIME_CANONICAL_IMAGE
        ),
    )
    build.add_argument(
        "--java-runtime-image",
        default=os.environ.get(
            "JAVA_RUNTIME_IMAGE", JAVA_RUNTIME_CANONICAL_IMAGE
        ),
        help="Actual Java runtime source image; may use a deployment registry mirror.",
    )
    build.add_argument(
        "--node-version",
        default=os.environ.get("NODE_VERSION", "22.22.2"),
    )
    build.add_argument(
        "--rebuild",
        action="store_true",
        help="Ignore exact-SHA image cache and rebuild base/profile images.",
    )
    args = parser.parse_args(argv)

    try:
        data = _load_catalog()
        profiles = _profile_map(data)
        if args.command == "validate":
            _print_json(validate_catalog(data, profiles))
            return 0
        if args.command == "list":
            for profile_id in sorted(profiles):
                row = profiles[profile_id]
                print(
                    json.dumps(
                        {
                            "profile_id": profile_id,
                            "category_id": row["category_id"],
                            "build_mode": row.get("build_mode", "environment-image"),
                            "compose": row.get("compose"),
                        },
                        sort_keys=True,
                    )
                )
            return 0
        if args.command == "show":
            try:
                _print_json(profiles[args.profile_id])
            except KeyError:
                print(f"unknown environment profile: {args.profile_id}", file=sys.stderr)
                return 2
            return 0

        build_environment_images(
            profiles=tuple(args.profiles),
            work_root=args.work_root,
            output=args.output,
            python_runtime_image=args.python_runtime_image,
            python_runtime_canonical_image=args.python_runtime_canonical_image,
            java_runtime_image=args.java_runtime_image,
            java_runtime_canonical_image=args.java_runtime_canonical_image,
            node_version=args.node_version,
            rebuild=args.rebuild,
        )
    except Exception as exc:
        print(
            f"ENVIRONMENT_IMAGE_FAIL {type(exc).__qualname__}: {exc}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

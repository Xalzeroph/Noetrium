from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Iterable
import uuid

from noetrium_platform.foundation.kernel.concurrency.api import (
    ContentAddressedSingleFlight,
)
from noetrium_platform.composition.runtime_coordination import (
    runtime_coordination_root,
)

_ENVIRONMENT_SINGLE_FLIGHT = ContentAddressedSingleFlight(
    runtime_coordination_root() / "global-single-flight"
)

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "deploy" / "environments" / "catalog.json"
PROFILE_REGISTRY_SCHEMA = "noetrium.environment-profile-registry.v3"
PROFILE_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")
BUILD_INPUT_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
PROFILE_LIFECYCLE_STATES = frozenset({"active", "draining", "retired"})
REQUIRED_PRIVATE_WRITABLE = frozenset({
    "workspace",
    "tmp",
    "runtime-state",
    "secrets",
    "process-namespace",
    "network-namespace",
    "ports",
})
FORBIDDEN_IMAGE_MARKERS = (
    "copy research",
    "copy benchmarks",
    "copy datasets",
    "copy checkpoints",
    "copy experiments",
)
PROFILE_ID_LABEL = "org.opencontainers.image.noetrium.environment.profile-id"
PROFILE_CATEGORY_LABEL = "org.opencontainers.image.noetrium.environment.category-id"
PROFILE_REVISION_LABEL = "org.opencontainers.image.noetrium.environment.profile-revision"
PROFILE_BUILD_INPUT_LABEL = "org.opencontainers.image.noetrium.environment.build-input.sha256"
PYTHON_RUNTIME_IDENTITY_LABEL = "org.opencontainers.image.noetrium.python-runtime.sha256"
ENVIRONMENT_BASE_REVISION_LABEL = "org.opencontainers.image.noetrium.environment.base-revision"
ENVIRONMENT_BASE_BUILD_INPUT_LABEL = "org.opencontainers.image.noetrium.environment.base-build-input.sha256"
PYTHON_RUNTIME_CANONICAL_IMAGE = "python:3.12-slim-bookworm"

_QUALIFICATION_CHILD_LABEL = "io.noetrium.bootstrap-child=qualification-v1"
_QUALIFICATION_OWNER_ENV = (
    ("NOETRIUM_BOOTSTRAP_OWNER_PID", "io.noetrium.bootstrap-owner-pid"),
    ("NOETRIUM_BOOTSTRAP_OWNER_BOOT", "io.noetrium.bootstrap-owner-boot"),
    ("NOETRIUM_BOOTSTRAP_OWNER_START", "io.noetrium.bootstrap-owner-start"),
)



_ENVIRONMENT_QUALIFICATION_SCHEMA = "noetrium.environment-profile-qualification.v1"


def _qualification_material(
    *,
    profile_id: str,
    category_id: str,
    image_identity: dict,
    profile_revision: str,
    build_input_digest: str,
    doctor_sha256: str,
) -> dict[str, str]:
    return {
        "schema": _ENVIRONMENT_QUALIFICATION_SCHEMA,
        "profile_id": profile_id,
        "category_id": category_id,
        "image_runtime_identity_digest": _image_runtime_identity_digest(image_identity),
        "profile_revision": profile_revision,
        "build_input_digest": build_input_digest,
        "doctor_sha256": doctor_sha256,
    }


def _qualification_digest(material: dict[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(
            material, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    ).hexdigest()


def _qualification_receipt_path(
    work_root: Path, profile_id: str, qualification_digest: str
) -> Path:
    return (
        work_root
        / "content"
        / "qualification-receipts"
        / profile_id
        / f"{qualification_digest}.json"
    )


def _legacy_qualification_receipt_path(
    work_root: Path, profile_id: str, qualification_digest: str
) -> Path:
    return (
        work_root
        / "qualification-receipts"
        / profile_id
        / f"{qualification_digest}.json"
    )


def _load_qualification_receipt(
    path: Path, *, material: dict[str, str], qualification_digest: str
) -> dict | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        type(data) is not dict
        or data.get("status") != "pass"
        or data.get("qualification_digest") != qualification_digest
        or data.get("material") != material
    ):
        return None
    return data


def _publish_qualification_receipt(
    path: Path, *, material: dict[str, str], qualification_digest: str
) -> dict:
    receipt = {
        "schema": _ENVIRONMENT_QUALIFICATION_SCHEMA,
        "status": "pass",
        "qualification_digest": qualification_digest,
        "material": material,
    }
    content_root = path.parents[2]
    receipt_root = path.parents[1]
    profile_root = path.parent
    for directory in (content_root, receipt_root, profile_root):
        _ensure_runtime_writable_directory(directory)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}-{uuid.uuid4().hex}")
    temporary.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)
    return receipt


def _qualify_profile_once(
    *,
    work_root: Path,
    profile_id: str,
    category_id: str,
    image_identity: dict,
    profile_revision: str,
    build_input_digest: str,
    rebuild: bool,
    doctor: Path,
    run_doctor,
) -> tuple[dict, bool]:
    material = _qualification_material(
        profile_id=profile_id,
        category_id=category_id,
        image_identity=image_identity,
        profile_revision=profile_revision,
        build_input_digest=build_input_digest,
        doctor_sha256=_sha256(doctor),
    )
    digest = _qualification_digest(material)
    path = _qualification_receipt_path(work_root, profile_id, digest)
    with _ENVIRONMENT_SINGLE_FLIGHT.producer(
        "environment-qualification",
        f"qualification:{profile_id}:{digest}",
    ):
        cached = None if rebuild else _load_qualification_receipt(
            path, material=material, qualification_digest=digest
        )
        if cached is not None:
            return cached, True
        if not rebuild:
            legacy_path = _legacy_qualification_receipt_path(
                work_root,
                profile_id,
                digest,
            )
            legacy = _load_qualification_receipt(
                legacy_path,
                material=material,
                qualification_digest=digest,
            )
            if legacy is not None:
                migrated = _publish_qualification_receipt(
                    path,
                    material=material,
                    qualification_digest=digest,
                )
                return migrated, True
        run_doctor()
        return (
            _publish_qualification_receipt(
                path, material=material, qualification_digest=digest
            ),
            False,
        )











def _qualification_label_args() -> tuple[str, ...]:
    args: list[str] = ["--label", _QUALIFICATION_CHILD_LABEL]
    for env_name, label_name in _QUALIFICATION_OWNER_ENV:
        value = os.environ.get(env_name, "").strip()
        if value:
            args.extend(("--label", f"{label_name}={value}"))
    return tuple(args)



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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _qualification_instance_mounts(compose_path: Path) -> tuple[Path, ...]:
    """Return profile-private bind subdirectories declared by Compose.

    Docker creates a missing bind source on the daemon host, commonly as root.
    Qualification containers run as the unprivileged platform user, so every
    profile-owned writable source must exist with usable permissions before
    Compose is allowed to materialize the container.
    """

    text = compose_path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"\$\{PLATFORM_ENVIRONMENT_INSTANCE_ROOT[^}]*\}"
        r"/([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)"
    )
    rows: set[Path] = set()
    for match in pattern.finditer(text):
        relative = Path(match.group(1))
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(
                f"unsafe environment instance bind source in {compose_path}: {relative}"
            )
        rows.add(relative)
    return tuple(sorted(rows, key=lambda value: value.as_posix()))


def _ensure_runtime_writable_directory(path: Path) -> None:
    """Ensure a cross-container runtime directory is usable without owner churn."""
    existed = path.exists()
    path.mkdir(parents=True, exist_ok=True)
    if not existed:
        try:
            path.chmod(0o777)
        except PermissionError:
            pass
    if os.access(path, os.W_OK | os.X_OK):
        return
    try:
        path.chmod(0o777)
    except PermissionError:
        pass
    if not os.access(path, os.W_OK | os.X_OK):
        raise RuntimeError(
            f"environment runtime directory is not writable/executable: {path}"
        )


def _prepare_qualification_instance(
    qualification_instance: Path,
    *,
    compose_path: Path,
) -> None:
    if qualification_instance.exists():
        shutil.rmtree(qualification_instance)
    _ensure_runtime_writable_directory(qualification_instance)

    writable = (Path("platform-state"), *_qualification_instance_mounts(compose_path))
    for relative in writable:
        target = qualification_instance / relative
        _ensure_runtime_writable_directory(target)


def _load_catalog() -> dict:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if data.get("schema") != PROFILE_REGISTRY_SCHEMA:
        raise RuntimeError("environment profile registry schema is not current")
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
        if (
            not isinstance(profile_id, str)
            or PROFILE_TOKEN_RE.fullmatch(profile_id) is None
        ):
            raise RuntimeError(
                "environment profile id must be a lowercase deployment token"
            )
        if profile_id in result:
            raise RuntimeError(f"duplicate environment profile id: {profile_id}")
        result[profile_id] = row
    return result


def _profile_build_input_rows(
    row: dict,
) -> tuple[tuple[dict, ...], tuple[dict, ...]]:
    raw = row.get("build_inputs", {})
    if not isinstance(raw, dict):
        raise RuntimeError("profile build_inputs must be an object")
    images = raw.get("images", [])
    parameters = raw.get("parameters", [])
    if not isinstance(images, list) or not isinstance(parameters, list):
        raise RuntimeError(
            "profile build_inputs images/parameters must be lists"
        )

    seen_names: set[str] = set()
    seen_environment_variables: set[str] = set()

    def validate_common(spec: object, *, kind: str) -> dict:
        if not isinstance(spec, dict):
            raise RuntimeError(f"profile build input {kind} must be an object")
        name = spec.get("name")
        environment_variable = spec.get("environment_variable")
        if (
            not isinstance(name, str)
            or PROFILE_TOKEN_RE.fullmatch(name) is None
        ):
            raise RuntimeError(
                f"profile build input {kind} name must be a deployment token"
            )
        if (
            not isinstance(environment_variable, str)
            or BUILD_INPUT_ENV_RE.fullmatch(environment_variable) is None
        ):
            raise RuntimeError(
                f"profile build input {kind} environment_variable "
                "must be an uppercase environment token"
            )
        if name in seen_names:
            raise RuntimeError(f"duplicate profile build input name: {name}")
        if environment_variable in seen_environment_variables:
            raise RuntimeError(
                "duplicate profile build input environment variable: "
                + environment_variable
            )
        seen_names.add(name)
        seen_environment_variables.add(environment_variable)
        return spec

    normalized_images: list[dict] = []
    for raw_spec in images:
        spec = validate_common(raw_spec, kind="image")
        if set(spec) != {
            "name",
            "environment_variable",
            "canonical_image",
        }:
            raise RuntimeError(
                "profile image build input fields must be exactly "
                "name/environment_variable/canonical_image"
            )
        canonical_image = spec["canonical_image"]
        if (
            not isinstance(canonical_image, str)
            or not canonical_image.strip()
            or canonical_image != canonical_image.strip()
        ):
            raise RuntimeError(
                "profile image build input canonical_image "
                "must be canonical non-empty text"
            )
        normalized_images.append(dict(spec))

    normalized_parameters: list[dict] = []
    for raw_spec in parameters:
        spec = validate_common(raw_spec, kind="parameter")
        if set(spec) != {
            "name",
            "environment_variable",
            "default",
        }:
            raise RuntimeError(
                "profile parameter build input fields must be exactly "
                "name/environment_variable/default"
            )
        default = spec["default"]
        if (
            not isinstance(default, str)
            or not default.strip()
            or default != default.strip()
        ):
            raise RuntimeError(
                "profile parameter build input default "
                "must be canonical non-empty text"
            )
        normalized_parameters.append(dict(spec))

    return (
        tuple(sorted(normalized_images, key=lambda row: row["name"])),
        tuple(sorted(normalized_parameters, key=lambda row: row["name"])),
    )


def _parse_profile_build_input_overrides(
    values: tuple[str, ...],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in values:
        environment_variable, separator, value = raw.partition("=")
        if (
            separator != "="
            or BUILD_INPUT_ENV_RE.fullmatch(environment_variable) is None
            or not value
        ):
            raise ValueError(
                "profile build input override must use ENVIRONMENT_VARIABLE=value"
            )
        if environment_variable in result:
            raise ValueError(
                "duplicate profile build input override: "
                + environment_variable
            )
        result[environment_variable] = value
    return result


def _parse_profile_build_input_env_file(
    path: Path | None,
    *,
    declared_environment_variables: set[str],
) -> dict[str, str]:
    if path is None:
        return {}
    if not path.is_file():
        raise ValueError(f"profile build input env file does not exist: {path}")
    result: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        environment_variable, separator, value = line.partition("=")
        environment_variable = environment_variable.strip()
        if environment_variable not in declared_environment_variables:
            continue
        value = value.strip()
        if separator != "=" or not value:
            raise ValueError(
                "profile build input env file contains invalid declared value "
                f"at line {line_number}: {environment_variable!r}"
            )
        if environment_variable in result:
            raise ValueError(
                "duplicate profile build input env file value: "
                + environment_variable
            )
        result[environment_variable] = value
    return result


def _profile_revision(row: dict) -> str:
    """Digest only bytes/identity that can change the built image."""
    recipe_digests: dict[str, str] = {}
    dockerfile = row.get("dockerfile")
    if isinstance(dockerfile, str) and dockerfile:
        path = ROOT / dockerfile
        if not path.is_file():
            raise FileNotFoundError(path)
        recipe_digests["dockerfile"] = _sha256(path)

    category_id = row.get("category_id")
    if isinstance(category_id, str) and row.get("build_mode") != "base-only":
        doctor = ROOT / "deploy" / "environments" / category_id / "doctor.sh"
        if not doctor.is_file():
            raise FileNotFoundError(doctor)
        recipe_digests["doctor"] = _sha256(doctor)

    content_inputs = row.get("content_inputs", [])
    if not isinstance(content_inputs, list) or any(
        not isinstance(value, str) or not value for value in content_inputs
    ):
        raise RuntimeError("profile content_inputs must be a list of paths")
    for relative in sorted(content_inputs):
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        recipe_digests[f"content:{relative}"] = _sha256(path)

    material = {
        "schema": "noetrium.environment-profile-image-revision.v1",
        "profile_id": row["profile_id"],
        "category_id": row["category_id"],
        "build_mode": row.get("build_mode"),
        "recipe_digests": recipe_digests,
    }
    return hashlib.sha256(
        json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _profile_runtime_revision(row: dict, *, image_revision: str) -> str:
    """Digest runtime orchestration/policy without poisoning image reuse."""
    compose = row.get("compose")
    compose_sha256 = None
    if isinstance(compose, str) and compose:
        path = ROOT / compose
        if not path.is_file():
            raise FileNotFoundError(path)
        compose_sha256 = _sha256(path)
    material = {
        "schema": "noetrium.environment-profile-runtime-revision.v1",
        "profile_id": row["profile_id"],
        "category_id": row["category_id"],
        "image_revision": image_revision,
        "compose_sha256": compose_sha256,
        "extends": row.get("extends"),
        "build_mode": row.get("build_mode"),
        "runtime_sharing": row.get("runtime_sharing"),
        "isolation": row.get("isolation"),
        "boundary": row.get("boundary"),
    }
    return hashlib.sha256(
        json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _default_active_profile_ids(profiles: dict[str, dict]) -> tuple[str, ...]:
    return tuple(
        sorted(
            profile_id
            for profile_id, row in profiles.items()
            if row.get("lifecycle") == "active"
            and row.get("default_for_category") is True
        )
    )


def _require_profile_build_intent(
    profiles: dict[str, dict],
    selected: tuple[str, ...],
    *,
    allow_draining: bool,
    allow_retired: bool,
) -> None:
    for profile_id in selected:
        lifecycle = profiles[profile_id].get("lifecycle")
        if lifecycle == "draining" and not allow_draining:
            raise RuntimeError(
                f"{profile_id}: draining profile requires explicit "
                "--allow-draining recovery intent"
            )
        if lifecycle == "retired" and not allow_retired:
            raise RuntimeError(
                f"{profile_id}: retired profile requires explicit "
                "--allow-retired historical recovery intent"
            )


def validate_catalog(data: dict, profiles: dict[str, dict]) -> dict:
    errors: list[str] = []
    if not profiles:
        errors.append("environment profile registry must contain at least one profile")

    base = data.get("base")
    if not isinstance(base, dict):
        errors.append("base image authority must be an object")
    else:
        if base.get("build_mode") != "dependency-runtime":
            errors.append("base image must remain dependency-runtime")
        for field in ("dockerfile", "compose"):
            value = base.get(field)
            if not isinstance(value, str) or not value:
                errors.append(f"base {field} must be non-empty")
            elif not (ROOT / value).is_file():
                errors.append(f"base {field} does not exist: {value}")
        content_inputs = base.get("content_inputs")
        if not isinstance(content_inputs, list) or not content_inputs:
            errors.append("base content_inputs must be non-empty")
        else:
            for relative in content_inputs:
                if not isinstance(relative, str) or not relative:
                    errors.append("base content_inputs must contain paths")
                elif not (ROOT / relative).is_file():
                    errors.append(f"base content input does not exist: {relative}")

    active_defaults: dict[str, list[str]] = {}
    for profile_id, row in sorted(profiles.items()):
        category_id = row.get("category_id")
        if (
            not isinstance(category_id, str)
            or PROFILE_TOKEN_RE.fullmatch(category_id) is None
        ):
            errors.append(
                f"{profile_id}: category_id must be a lowercase deployment token"
            )
            continue

        lifecycle = row.get("lifecycle")
        if lifecycle not in PROFILE_LIFECYCLE_STATES:
            errors.append(
                f"{profile_id}: lifecycle must be one of "
                f"{sorted(PROFILE_LIFECYCLE_STATES)!r}"
            )
        if row.get("default_for_category") is True:
            if lifecycle != "active":
                errors.append(
                    f"{profile_id}: only active profiles may be category defaults"
                )
            active_defaults.setdefault(category_id, []).append(profile_id)

        if row.get("extends") != "base":
            errors.append(f"{profile_id}: environment profile must extend base")

        isolation = row.get("isolation")
        if not isinstance(isolation, dict):
            errors.append(f"{profile_id}: isolation policy must be an object")
        else:
            shared = isolation.get("shared_read_only")
            private = isolation.get("private_writable")
            cleanliness = isolation.get("cleanliness")
            if not isinstance(shared, list) or not shared:
                errors.append(f"{profile_id}: shared_read_only must be non-empty")
            if not isinstance(private, list):
                errors.append(f"{profile_id}: private_writable must be a list")
            else:
                missing = sorted(REQUIRED_PRIVATE_WRITABLE - set(private))
                if missing:
                    errors.append(
                        f"{profile_id}: private_writable misses required isolation "
                        f"domains {missing!r}"
                    )
            if cleanliness != "destroy-overlay-or-verified-reset":
                errors.append(
                    f"{profile_id}: cleanliness policy must require overlay "
                    "destruction or verified reset"
                )

        try:
            build_input_images, build_input_parameters = (
                _profile_build_input_rows(row)
            )
        except RuntimeError as exc:
            errors.append(f"{profile_id}: {exc}")
            build_input_images = ()
            build_input_parameters = ()

        if row.get("build_mode") == "base-only":
            if build_input_images or build_input_parameters:
                errors.append(
                    f"{profile_id}: base-only profile cannot declare "
                    "profile build inputs"
                )
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
            if "arg platform_environment_base_image" not in lowered:
                errors.append(f"{profile_id}: Dockerfile must declare PLATFORM_ENVIRONMENT_BASE_IMAGE")
            if "from ${platform_environment_base_image}" not in lowered:
                errors.append(f"{profile_id}: Dockerfile must consume PLATFORM_ENVIRONMENT_BASE_IMAGE")
            if "environment-doctor.d" not in lowered:
                errors.append(
                    f"{profile_id}: Dockerfile must install a profile-local doctor hook"
                )
            for label in (
                PROFILE_ID_LABEL,
                PROFILE_CATEGORY_LABEL,
                PROFILE_REVISION_LABEL,
                PROFILE_BUILD_INPUT_LABEL,
            ):
                if label not in dockerfile_text:
                    errors.append(
                        f"{profile_id}: Dockerfile must carry profile identity label {label}"
                    )
            for marker in FORBIDDEN_IMAGE_MARKERS:
                if marker in lowered:
                    errors.append(
                        f"{profile_id}: downstream/scientific marker leaked into image: "
                        f"{marker}"
                    )
        if compose_text:
            if "environment-doctor" not in compose_text:
                errors.append(f"{profile_id}: compose overlay lacks environment doctor")
            if category_id not in compose_text:
                errors.append(
                    f"{profile_id}: compose overlay lacks category identity {category_id!r}"
                )
            for build_arg in (
                "NOETRIUM_ENVIRONMENT_PROFILE_ID",
                "NOETRIUM_ENVIRONMENT_CATEGORY_ID",
                "NOETRIUM_ENVIRONMENT_PROFILE_REVISION",
                "NOETRIUM_ENVIRONMENT_BUILD_INPUT_DIGEST",
            ):
                if build_arg not in compose_text:
                    errors.append(
                        f"{profile_id}: compose overlay lacks identity build arg {build_arg}"
                    )
            for spec in (*build_input_images, *build_input_parameters):
                environment_variable = spec["environment_variable"]
                if environment_variable not in compose_text:
                    errors.append(
                        f"{profile_id}: compose overlay does not consume "
                        f"declared build input {environment_variable}"
                    )

    for category_id, defaults in sorted(active_defaults.items()):
        if len(defaults) != 1:
            errors.append(
                f"{category_id}: expected exactly one active default profile, "
                f"observed={defaults!r}"
            )
    active_categories = {
        row["category_id"]
        for row in profiles.values()
        if row.get("lifecycle") == "active"
    }
    missing_defaults = sorted(set(active_categories) - set(active_defaults))
    if missing_defaults:
        errors.append(
            "active categories lack a default profile: "
            f"{missing_defaults!r}"
        )

    if errors:
        raise RuntimeError("; ".join(errors))
    return {
        "schema": "noetrium.environment-profile-validation.v2",
        "status": "pass",
        "profile_count": len(profiles),
        "active_profile_count": sum(
            row.get("lifecycle") == "active" for row in profiles.values()
        ),
        "draining_profile_count": sum(
            row.get("lifecycle") == "draining" for row in profiles.values()
        ),
        "retired_profile_count": sum(
            row.get("lifecycle") == "retired" for row in profiles.values()
        ),
        "image_profile_count": sum(
            1 for row in profiles.values() if row.get("build_mode") != "base-only"
        ),
        "base_build_mode": data["base"]["build_mode"],
    }





def _identity_from_inspect_document(tag: str, data: dict) -> dict:
    return {
        "tag": tag,
        "id": data.get("Id"),
        "repo_digests": data.get("RepoDigests") or [],
        "created": data.get("Created"),
        "labels": (data.get("Config") or {}).get("Labels") or {},
    }


def _inspect_image_identity(tag: str) -> dict | None:
    completed = subprocess.run(
        ("docker", "image", "inspect", tag, "--format", "{{json .}}"),
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    raw = completed.stdout.strip()
    if not raw:
        return None
    return _identity_from_inspect_document(tag, json.loads(raw))


def _batch_image_identities(tags: Iterable[str]) -> dict[str, dict] | None:
    unique = tuple(dict.fromkeys(str(tag) for tag in tags))
    if not unique:
        return {}
    completed = subprocess.run(
        (
            "docker",
            "image",
            "inspect",
            *unique,
            "--format",
            "{{json .}}",
        ),
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    rows = tuple(
        line.strip()
        for line in completed.stdout.splitlines()
        if line.strip()
    )
    if len(rows) != len(unique):
        return None
    return {
        tag: _identity_from_inspect_document(tag, json.loads(raw))
        for tag, raw in zip(unique, rows, strict=True)
    }


def _ensure_image_identities(tags: Iterable[str]) -> dict[str, dict]:
    unique = tuple(dict.fromkeys(str(tag) for tag in tags))
    batch = _batch_image_identities(unique)
    if batch is not None:
        return batch
    for tag in unique:
        if _inspect_image_identity(tag) is None:
            _run(("docker", "pull", tag))
    batch = _batch_image_identities(unique)
    if batch is None:
        raise RuntimeError(
            "unable to resolve concrete Docker identities for runtime images"
        )
    return batch


def _image_exists(tag: str) -> bool:
    return _inspect_image_identity(tag) is not None


def _image_identity(tag: str) -> dict:
    identity = _inspect_image_identity(tag)
    if identity is None:
        raise RuntimeError(f"Docker image does not exist: {tag}")
    return identity


def _image_runtime_identity_digest(identity: dict) -> str:
    """Return the concrete content identity of one Docker image."""

    image_id = identity.get("id")
    if (
        type(image_id) is not str
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id)
    ):
        raise RuntimeError("Docker image identity is not a content-addressed sha256")
    return image_id.removeprefix("sha256:")






def _environment_base_revision(base: dict) -> str:
    content_inputs = base.get("content_inputs")
    if not isinstance(content_inputs, list) or not content_inputs:
        raise RuntimeError("environment base content_inputs are required")
    content = {}
    for relative in sorted(content_inputs):
        if not isinstance(relative, str) or not relative:
            raise RuntimeError("environment base content input path is invalid")
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        content[relative] = _sha256(path)
    material = {
        "schema": "noetrium.environment-base-revision.v1",
        "build_mode": base.get("build_mode"),
        "content": content,
    }
    return hashlib.sha256(
        json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _environment_base_build_input_digest(
    *,
    base_revision: str,
    python_runtime_identity_digest: str,
) -> str:
    material = {
        "schema": "noetrium.environment-base-build-input.v1",
        "base_revision": base_revision,
        "python_runtime_identity_digest": python_runtime_identity_digest,
    }
    return hashlib.sha256(
        json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _environment_base_tag(build_input_digest: str) -> str:
    return f"noetrium-env-base:{build_input_digest}"


def _validate_environment_base_identity(
    identity: dict,
    *,
    base_revision: str,
    build_input_digest: str,
    python_runtime_identity_digest: str,
) -> dict:
    labels = identity.get("labels")
    if not isinstance(labels, dict):
        raise RuntimeError("environment base image labels are invalid")
    expected = {
        ENVIRONMENT_BASE_REVISION_LABEL: base_revision,
        ENVIRONMENT_BASE_BUILD_INPUT_LABEL: build_input_digest,
        PYTHON_RUNTIME_IDENTITY_LABEL: python_runtime_identity_digest,
    }
    mismatches = {
        key: (value, labels.get(key))
        for key, value in expected.items()
        if labels.get(key) != value
    }
    if mismatches:
        raise RuntimeError(
            f"environment base provenance mismatch: {mismatches!r}"
        )
    return identity


def _verified_environment_base_identity(
    tag: str,
    *,
    base_revision: str,
    build_input_digest: str,
    python_runtime_identity_digest: str,
) -> dict:
    return _validate_environment_base_identity(
        _image_identity(tag),
        base_revision=base_revision,
        build_input_digest=build_input_digest,
        python_runtime_identity_digest=python_runtime_identity_digest,
    )




def _ensure_image_identity(image: str) -> dict:
    """Resolve the concrete local image that will be consumed by Docker."""

    if not _image_exists(image):
        _run(("docker", "pull", image))
    return _image_identity(image)


def _resolve_profile_build_inputs(
    row: dict,
    *,
    overrides: dict[str, str],
    image_identity_cache: dict[str, dict],
) -> tuple[dict[str, str], dict[str, object]]:
    image_specs, parameter_specs = _profile_build_input_rows(row)
    environment: dict[str, str] = {}
    images: dict[str, dict[str, object]] = {}
    parameters: dict[str, dict[str, str]] = {}

    for spec in image_specs:
        environment_variable = spec["environment_variable"]
        canonical_image = spec["canonical_image"]
        source_image = overrides.get(
            environment_variable,
            os.environ.get(environment_variable, canonical_image),
        )
        if source_image not in image_identity_cache:
            image_identity_cache[source_image] = _ensure_image_identity(
                source_image
            )
        source_identity = image_identity_cache[source_image]
        environment[environment_variable] = source_image
        images[spec["name"]] = {
            "environment_variable": environment_variable,
            "canonical_image": canonical_image,
            "source_image": source_image,
            "source_identity": source_identity,
            "runtime_identity_digest": _image_runtime_identity_digest(
                source_identity
            ),
        }

    for spec in parameter_specs:
        environment_variable = spec["environment_variable"]
        value = overrides.get(
            environment_variable,
            os.environ.get(environment_variable, spec["default"]),
        )
        if not value:
            raise RuntimeError(
                f"profile build input {environment_variable} resolved empty"
            )
        environment[environment_variable] = value
        parameters[spec["name"]] = {
            "environment_variable": environment_variable,
            "value": value,
        }

    return environment, {
        "images": images,
        "parameters": parameters,
    }


def _profile_build_input_digest(
    row: dict,
    *,
    profile_revision: str,
    base_runtime_identity_digest: str,
    resolved_build_inputs: dict[str, object],
) -> str:
    images = resolved_build_inputs["images"]
    parameters = resolved_build_inputs["parameters"]
    material: dict[str, object] = {
        "schema": "noetrium.environment-profile-build-input.v2",
        "profile_id": row["profile_id"],
        "category_id": row["category_id"],
        "profile_revision": profile_revision,
        "base_runtime_identity_digest": base_runtime_identity_digest,
        "images": {
            name: value["runtime_identity_digest"]
            for name, value in sorted(images.items())
        },
        "parameters": {
            name: value["value"]
            for name, value in sorted(parameters.items())
        },
    }
    return hashlib.sha256(
        json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _validate_profile_image_identity(
    identity: dict,
    *,
    profile_id: str,
    category_id: str,
    profile_revision: str,
    build_input_digest: str,
) -> dict:
    labels = identity["labels"]
    expected = {
        PROFILE_ID_LABEL: profile_id,
        PROFILE_CATEGORY_LABEL: category_id,
        PROFILE_REVISION_LABEL: profile_revision,
        PROFILE_BUILD_INPUT_LABEL: build_input_digest,
    }
    mismatches = {
        key: (expected_value, labels.get(key))
        for key, expected_value in expected.items()
        if labels.get(key) != expected_value
    }
    if mismatches:
        raise RuntimeError(
            f"environment profile image identity mismatch for {tag}: {mismatches!r}"
        )
    return identity


def _verified_profile_image_identity(
    tag: str,
    *,
    profile_id: str,
    category_id: str,
    profile_revision: str,
    build_input_digest: str,
) -> dict:
    return _validate_profile_image_identity(
        _image_identity(tag),
        profile_id=profile_id,
        category_id=category_id,
        profile_revision=profile_revision,
        build_input_digest=build_input_digest,
    )


def _publish_image_alias(
    *,
    work_root: Path,
    source: str,
    alias: str,
    expected_image_id: str,
) -> dict:
    """Publish one mutable Docker alias under a shared per-alias fence."""

    with _ENVIRONMENT_SINGLE_FLIGHT.producer(
        "environment-image-alias",
        f"alias:{alias}",
    ):
        current = _inspect_image_identity(alias)
        if current is not None and current.get("id") == expected_image_id:
            return current
        if current is not None:
            _run(("docker", "image", "rm", alias))
        _run(("docker", "tag", source, alias))
        current = _image_identity(alias)
        if current.get("id") != expected_image_id:
            raise RuntimeError(
                "published Docker alias does not resolve to expected image: "
                f"{alias}"
            )
    return current


def _category_current_tag(category_id: str) -> str:
    if PROFILE_TOKEN_RE.fullmatch(category_id) is None:
        raise ValueError("environment category id is not a deployment token")
    return f"noetrium-env-category-{category_id}:current"


def _publish_category_current_alias(
    tag: str,
    *,
    work_root: Path,
    profile_id: str,
    category_id: str,
    profile_revision: str,
    build_input_digest: str,
    immutable_identity: dict,
) -> str:
    current_tag = _category_current_tag(category_id)
    current_identity = _publish_image_alias(
        work_root=work_root,
        source=tag,
        alias=current_tag,
        expected_image_id=str(immutable_identity["id"]),
    )
    current_identity = _validate_profile_image_identity(
        current_identity,
        profile_id=profile_id,
        category_id=category_id,
        profile_revision=profile_revision,
        build_input_digest=build_input_digest,
    )
    if current_identity.get("id") != immutable_identity.get("id"):
        raise RuntimeError(
            "environment profile current alias does not resolve to the qualified image"
        )
    return current_tag


def build_environment_images(
    *,
    profiles: tuple[str, ...],
    work_root: Path,
    output: Path,
    python_runtime_image: str,
    python_runtime_canonical_image: str,
    profile_build_input_overrides: dict[str, str],
    profile_build_input_env_file: Path | None = None,
    rebuild: bool = False,
    allow_draining: bool = False,
    allow_retired: bool = False,
) -> dict:
    catalog = _load_catalog()
    by_id = _profile_map(catalog)
    unknown = tuple(sorted(set(profiles) - set(by_id)))
    if unknown:
        raise RuntimeError(f"unknown environment profiles: {unknown!r}")
    validate_catalog(catalog, by_id)
    _require_profile_build_intent(
        by_id,
        profiles,
        allow_draining=allow_draining,
        allow_retired=allow_retired,
    )
    declared_build_input_variables = {
        spec["environment_variable"]
        for profile_id in profiles
        for group in _profile_build_input_rows(by_id[profile_id])
        for spec in group
    }
    env_file_build_input_overrides = _parse_profile_build_input_env_file(
        profile_build_input_env_file,
        declared_environment_variables=declared_build_input_variables,
    )
    resolved_profile_build_input_overrides = {
        **env_file_build_input_overrides,
        **profile_build_input_overrides,
    }
    unknown_build_input_overrides = tuple(
        sorted(
            set(resolved_profile_build_input_overrides)
            - declared_build_input_variables
        )
    )
    if unknown_build_input_overrides:
        raise RuntimeError(
            "profile build input overrides are not declared by selected "
            f"profiles: {unknown_build_input_overrides!r}"
        )

    if os.environ.get("NOETRIUM_DOCKER_CAPABILITY_VERIFIED") != "1":
        _run(("docker", "compose", "version"))

    work_root = work_root.resolve()
    runtime_root = work_root / "runtime"
    shared_root = runtime_root / "shared"
    instances_root = runtime_root / "instances"
    _ensure_runtime_writable_directory(shared_root)
    _ensure_runtime_writable_directory(instances_root)

    source_runtime_images: list[str] = [python_runtime_image]
    for profile_id in profiles:
        image_specs, _ = _profile_build_input_rows(by_id[profile_id])
        for spec in image_specs:
            environment_variable = spec["environment_variable"]
            source_runtime_images.append(
                resolved_profile_build_input_overrides.get(
                    environment_variable,
                    os.environ.get(
                        environment_variable,
                        spec["canonical_image"],
                    ),
                )
            )
    profile_input_image_cache = _ensure_image_identities(source_runtime_images)
    python_source_identity = profile_input_image_cache[python_runtime_image]
    python_runtime_identity_digest = _image_runtime_identity_digest(
        python_source_identity
    )

    base_spec = catalog["base"]
    base_revision = _environment_base_revision(base_spec)
    base_build_input_digest = _environment_base_build_input_digest(
        base_revision=base_revision,
        python_runtime_identity_digest=python_runtime_identity_digest,
    )
    base_tag = _environment_base_tag(base_build_input_digest)
    with _ENVIRONMENT_SINGLE_FLIGHT.producer(
        "environment-image",
        f"build:base:{base_build_input_digest}",
    ):
        base_identity = None if rebuild else _inspect_image_identity(base_tag)
        reused_base = base_identity is not None
        if not reused_base:
            base_env = os.environ.copy()
            base_env["PYTHON_RUNTIME_IMAGE"] = python_runtime_image
            base_env["PLATFORM_ENVIRONMENT_BASE_IMAGE"] = base_tag
            base_env["NOETRIUM_ENVIRONMENT_BASE_REVISION"] = base_revision
            base_env[
                "NOETRIUM_ENVIRONMENT_BASE_BUILD_INPUT_DIGEST"
            ] = base_build_input_digest
            base_env[
                "NOETRIUM_PYTHON_RUNTIME_IDENTITY_DIGEST"
            ] = python_runtime_identity_digest
            _run(
                (
                    "docker",
                    "build",
                    "--build-arg",
                    f"PYTHON_RUNTIME_IMAGE={python_runtime_image}",
                    "--build-arg",
                    f"NOETRIUM_ENVIRONMENT_BASE_REVISION={base_revision}",
                    "--build-arg",
                    (
                        "NOETRIUM_ENVIRONMENT_BASE_BUILD_INPUT_DIGEST="
                        f"{base_build_input_digest}"
                    ),
                    "--build-arg",
                    (
                        "NOETRIUM_PYTHON_RUNTIME_IDENTITY_DIGEST="
                        f"{python_runtime_identity_digest}"
                    ),
                    "--tag",
                    base_tag,
                    "--file",
                    str(ROOT / base_spec["dockerfile"]),
                    str(ROOT),
                ),
                env=base_env,
            )
            base_identity = _image_identity(base_tag)
        base_identity = _validate_environment_base_identity(
            base_identity,
            base_revision=base_revision,
            build_input_digest=base_build_input_digest,
            python_runtime_identity_digest=python_runtime_identity_digest,
        )

    base_doctor = ROOT / "deploy" / "environments" / "base" / "entrypoint.sh"
    base_qualification, base_qualification_reused = _qualify_profile_once(
        work_root=work_root,
        profile_id="base",
        category_id="base",
        image_identity=base_identity,
        profile_revision=base_revision,
        build_input_digest=base_build_input_digest,
        rebuild=rebuild,
        doctor=base_doctor,
        run_doctor=lambda: _run(
            (
                "docker",
                "run",
                "--rm",
                "--init",
                "--restart",
                "no",
                *_qualification_label_args(),
                base_tag,
                "environment-doctor",
                "base",
            )
        ),
    )
    build_mode = (
        "reused-environment-base"
        if reused_base
        else "built-environment-base"
    )
    base_identity["reused"] = reused_base
    base_identity["runtime_identity_digest"] = _image_runtime_identity_digest(
        base_identity
    )
    base_identity["base_revision"] = base_revision
    base_identity["build_input_digest"] = base_build_input_digest
    base_identity["qualification_digest"] = base_qualification[
        "qualification_digest"
    ]
    base_identity["qualification_reused"] = base_qualification_reused
    images: dict[str, dict] = {"base": base_identity}
    profile_build_inputs: dict[str, dict[str, object]] = {}
    for profile_id in profiles:
        row = by_id[profile_id]
        input_environment, resolved_build_inputs = (
            _resolve_profile_build_inputs(
                row,
                overrides=resolved_profile_build_input_overrides,
                image_identity_cache=profile_input_image_cache,
            )
        )
        profile_build_inputs[profile_id] = resolved_build_inputs
        if row.get("build_mode") == "base-only":
            profile_revision = _profile_revision(row)
            runtime_revision = _profile_runtime_revision(
                row, image_revision=profile_revision
            )
            build_input_digest = _profile_build_input_digest(
                row,
                profile_revision=profile_revision,
                base_runtime_identity_digest=base_identity[
                    "runtime_identity_digest"
                ],
                resolved_build_inputs=resolved_build_inputs,
            )
            doctor = base_doctor
            qualification, qualification_reused = _qualify_profile_once(
                work_root=work_root,
                profile_id=profile_id,
                category_id=row["category_id"],
                image_identity=base_identity,
                profile_revision=runtime_revision,
                build_input_digest=build_input_digest,
                rebuild=rebuild,
                doctor=doctor,
                run_doctor=lambda: _run(
                    (
                        "docker",
                        "run",
                        "--rm",
                        "--init",
                        "--restart",
                        "no",
                        *_qualification_label_args(),
                        base_tag,
                        "environment-doctor",
                        row["category_id"],
                    )
                ),
            )
            profile_identity = dict(base_identity)
            profile_identity["profile_id"] = profile_id
            profile_identity["profile_revision"] = profile_revision
            profile_identity["runtime_revision"] = runtime_revision
            profile_identity["build_input_digest"] = build_input_digest
            profile_identity["lifecycle"] = row["lifecycle"]
            profile_identity["base_only"] = True
            profile_identity["reused"] = True
            profile_identity["qualification_digest"] = qualification["qualification_digest"]
            profile_identity["qualification_reused"] = qualification_reused
            images[profile_id] = profile_identity
            continue

        compose = row.get("compose")
        image_env = row.get("image_env")
        if not isinstance(compose, str) or not compose:
            raise RuntimeError(f"{profile_id}: compose path missing")
        if not isinstance(image_env, str) or not image_env:
            raise RuntimeError(f"{profile_id}: image_env missing")
        revision = _profile_revision(row)
        runtime_revision = _profile_runtime_revision(
            row, image_revision=revision
        )
        build_input_digest = _profile_build_input_digest(
            row,
            profile_revision=revision,
            base_runtime_identity_digest=base_identity[
                "runtime_identity_digest"
            ],
            resolved_build_inputs=resolved_build_inputs,
        )
        tag = f"noetrium-env-{profile_id}:{build_input_digest}"
        env = os.environ.copy()
        env["PLATFORM_ENVIRONMENT_BASE_IMAGE"] = base_tag
        env[image_env] = tag
        env.update(input_environment)
        env["PLATFORM_HOST_DATA_ROOT"] = str(runtime_root)
        qualification_instance = (
            instances_root / f"doctor-{profile_id}-{build_input_digest[:24]}"
        )
        env["PLATFORM_ENVIRONMENT_INSTANCE_ROOT"] = str(qualification_instance)
        env["PLATFORM_RUNTIME_STATE_ROOT"] = str(
            qualification_instance / "platform-state"
        )
        env["NOETRIUM_ENVIRONMENT_INSTANCE_ID"] = qualification_instance.name
        env["NOETRIUM_ENVIRONMENT_PROFILE_ID"] = profile_id
        env["NOETRIUM_ENVIRONMENT_CATEGORY_ID"] = row["category_id"]
        env["NOETRIUM_ENVIRONMENT_PROFILE_REVISION"] = revision
        env["NOETRIUM_ENVIRONMENT_BUILD_INPUT_DIGEST"] = build_input_digest
        with _ENVIRONMENT_SINGLE_FLIGHT.producer(
            "environment-image",
            f"build:profile:{profile_id}:{build_input_digest}",
        ):
            profile_identity = None if rebuild else _inspect_image_identity(tag)
            reused_profile = profile_identity is not None
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
                profile_identity = _image_identity(tag)
        profile_identity = _validate_profile_image_identity(
            profile_identity,
            profile_id=profile_id,
            category_id=row["category_id"],
            profile_revision=revision,
            build_input_digest=build_input_digest,
        )
        doctor = ROOT / "deploy" / "environments" / row["category_id"] / "doctor.sh"

        def run_profile_doctor() -> None:
            _prepare_qualification_instance(
                qualification_instance, compose_path=ROOT / compose
            )
            try:
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
                        *_qualification_label_args(),
                        "platform-runtime",
                        "environment-doctor",
                        row["category_id"],
                    ),
                    env=env,
                )
            finally:
                if qualification_instance.exists():
                    shutil.rmtree(qualification_instance)

        qualification, qualification_reused = _qualify_profile_once(
            work_root=work_root,
            profile_id=profile_id,
            category_id=row["category_id"],
            image_identity=profile_identity,
            profile_revision=runtime_revision,
            build_input_digest=build_input_digest,
            rebuild=rebuild,
            doctor=doctor,
            run_doctor=run_profile_doctor,
        )
        profile_identity["reused"] = reused_profile
        profile_identity["runtime_identity_digest"] = _image_runtime_identity_digest(
            profile_identity
        )
        profile_identity["qualification_digest"] = qualification["qualification_digest"]
        profile_identity["qualification_reused"] = qualification_reused
        profile_identity["profile_revision"] = revision
        profile_identity["runtime_revision"] = runtime_revision
        profile_identity["build_input_digest"] = build_input_digest
        profile_identity["lifecycle"] = row["lifecycle"]
        profile_identity["qualification_instance_cleaned"] = True
        if row["lifecycle"] == "active" and row.get("default_for_category") is True:
            profile_identity["current_tag"] = _publish_category_current_alias(
                tag,
                work_root=work_root,
                profile_id=profile_id,
                category_id=row["category_id"],
                profile_revision=revision,
                build_input_digest=build_input_digest,
                immutable_identity=profile_identity,
            )
        images[profile_id] = profile_identity

    receipt = {
        "schema": "noetrium.environment-image-build.v5",
        "catalog_sha256": _sha256(CATALOG_PATH),
        "base_revision": base_revision,
        "base_build_input_digest": base_build_input_digest,
        "base_runtime_source": {
            "canonical_image": python_runtime_canonical_image,
            "source_image": python_runtime_image,
            "source_identity": python_source_identity,
            "runtime_identity_digest": python_runtime_identity_digest,
        },
        "profile_build_inputs": profile_build_inputs,
        "profiles": [
            {
                "profile_id": profile_id,
                "category_id": by_id[profile_id]["category_id"],
                "lifecycle": by_id[profile_id]["lifecycle"],
                "profile_revision": images[profile_id]["profile_revision"],
                "runtime_revision": images[profile_id]["runtime_revision"],
                "build_input_digest": images[profile_id][
                    "build_input_digest"
                ],
            }
            for profile_id in profiles
        ],
        "rebuild": rebuild,
        "allow_draining": allow_draining,
        "allow_retired": allow_retired,
        "build_mode": build_mode,
        "runtime_root": str(runtime_root),
        "images": images,
        "base_qualification": base_qualification,
        "base_qualification_reused": base_qualification_reused,
    }
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output_temporary = output.with_name(
        output.name + f".tmp-{os.getpid()}-{uuid.uuid4().hex}"
    )
    output_temporary.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(output_temporary, output)
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
        default=None,
        help=(
            "Explicit profile ids. When omitted, build the active default "
            "revision for every registered category."
        ),
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
        "--build-input",
        action="append",
        default=[],
        metavar="ENVIRONMENT_VARIABLE=value",
        help=(
            "Override one registry-declared profile build input. "
            "May be repeated; undeclared overrides fail closed."
        ),
    )
    build.add_argument(
        "--build-input-env-file",
        type=Path,
        default=None,
        help=(
            "Read only registry-declared profile build inputs from a deployment "
            "env file. Unrelated variables are ignored; explicit --build-input "
            "values take precedence."
        ),
    )
    build.add_argument(
        "--rebuild",
        action="store_true",
        help="Ignore exact-SHA image cache and rebuild base/profile images.",
    )
    build.add_argument(
        "--allow-draining",
        action="store_true",
        help=(
            "Permit explicitly named draining revisions only for resuming "
            "already-pinned executions. Draining profiles are never selected "
            "for new work by default."
        ),
    )
    build.add_argument(
        "--allow-retired",
        action="store_true",
        help=(
            "Permit explicitly named retired revisions for historical recovery. "
            "Retired profiles are never selected by default."
        ),
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
                            "lifecycle": row["lifecycle"],
                            "default_for_category": row.get(
                                "default_for_category", False
                            ),
                            "profile_revision": _profile_revision(row),
                            "runtime_revision": _profile_runtime_revision(
                                row, image_revision=_profile_revision(row)
                            ),
                            "build_mode": row.get(
                                "build_mode", "environment-image"
                            ),
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

        selected_profiles = (
            _default_active_profile_ids(profiles)
            if args.profiles is None
            else tuple(args.profiles)
        )
        if not selected_profiles:
            raise RuntimeError("no environment profiles selected for build")
        receipt = build_environment_images(
            profiles=selected_profiles,
            work_root=args.work_root,
            output=args.output,
            python_runtime_image=args.python_runtime_image,
            python_runtime_canonical_image=args.python_runtime_canonical_image,
            profile_build_input_overrides=(
                _parse_profile_build_input_overrides(
                    tuple(args.build_input)
                )
            ),
            profile_build_input_env_file=args.build_input_env_file,
            rebuild=args.rebuild,
            allow_draining=args.allow_draining,
            allow_retired=args.allow_retired,
        )
        _print_json(receipt)
    except Exception as exc:
        print(
            f"ENVIRONMENT_IMAGE_FAIL {type(exc).__qualname__}: {exc}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

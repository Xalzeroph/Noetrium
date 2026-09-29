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
WHEEL_LABEL = "org.opencontainers.image.noetrium.wheel.sha256"
DISTRIBUTION_LABEL = "org.opencontainers.image.noetrium.distribution-evidence.sha256"
REVISION_LABEL = "org.opencontainers.image.revision"
PROFILE_ID_LABEL = "org.opencontainers.image.noetrium.environment.profile-id"
PROFILE_CATEGORY_LABEL = "org.opencontainers.image.noetrium.environment.category-id"
PROFILE_REVISION_LABEL = "org.opencontainers.image.noetrium.environment.profile-revision"
PROFILE_BUILD_INPUT_LABEL = "org.opencontainers.image.noetrium.environment.build-input.sha256"
PYTHON_RUNTIME_IDENTITY_LABEL = "org.opencontainers.image.noetrium.python-runtime.sha256"
PYTHON_RUNTIME_CANONICAL_IMAGE = "python:3.12-slim-bookworm"

_QUALIFICATION_CHILD_LABEL = "io.noetrium.bootstrap-child=qualification-v1"
_QUALIFICATION_OWNER_ENV = (
    ("NOETRIUM_BOOTSTRAP_OWNER_PID", "io.noetrium.bootstrap-owner-pid"),
    ("NOETRIUM_BOOTSTRAP_OWNER_BOOT", "io.noetrium.bootstrap-owner-boot"),
    ("NOETRIUM_BOOTSTRAP_OWNER_START", "io.noetrium.bootstrap-owner-start"),
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


def _git(*args: str) -> str:
    return _run(("git", *args), capture=True)


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


def _prepare_qualification_instance(
    qualification_instance: Path,
    *,
    compose_path: Path,
) -> None:
    if qualification_instance.exists():
        shutil.rmtree(qualification_instance)
    qualification_instance.mkdir(parents=True)
    qualification_instance.chmod(0o777)

    writable = (Path("platform-state"), *_qualification_instance_mounts(compose_path))
    for relative in writable:
        target = qualification_instance / relative
        target.mkdir(parents=True, exist_ok=True)
        target.chmod(0o777)


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


def _profile_revision(row: dict) -> str:
    """Digest the immutable deployable profile definition and its recipe bytes."""
    material = {
        key: value
        for key, value in row.items()
        if key not in {"lifecycle", "default_for_category"}
    }
    recipe_digests: dict[str, str] = {}
    for field in ("dockerfile", "compose"):
        value = row.get(field)
        if isinstance(value, str) and value:
            path = ROOT / value
            if path.is_file():
                recipe_digests[field] = _sha256(path)
    category_id = row.get("category_id")
    if isinstance(category_id, str) and row.get("build_mode") != "base-only":
        doctor = ROOT / "deploy" / "environments" / category_id / "doctor.sh"
        if doctor.is_file():
            recipe_digests["doctor"] = _sha256(doctor)
    material["recipe_digests"] = recipe_digests
    payload = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
        if base.get("build_mode") != "evidence-bound-wheel":
            errors.append("base image must remain evidence-bound-wheel")
        for field in ("dockerfile", "compose"):
            value = base.get(field)
            if not isinstance(value, str) or not value:
                errors.append(f"base {field} must be non-empty")
            elif not (ROOT / value).is_file():
                errors.append(f"base {field} does not exist: {value}")

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
            if "arg platform_base_image" not in lowered:
                errors.append(f"{profile_id}: Dockerfile must declare PLATFORM_BASE_IMAGE")
            if "from ${platform_base_image}" not in lowered:
                errors.append(f"{profile_id}: Dockerfile must consume PLATFORM_BASE_IMAGE")
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

def _digest_label(labels: dict, key: str) -> str:
    value = labels.get(key)
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise RuntimeError(f"cached base image has invalid provenance label: {key}")
    return value


def _cached_base_provenance(
    identity: dict,
    source_sha: str,
    python_runtime_identity_digest: str,
) -> tuple[str, str]:
    labels = identity.get("labels")
    if not isinstance(labels, dict):
        raise RuntimeError("cached base image labels are invalid")
    if labels.get(REVISION_LABEL) != source_sha:
        raise RuntimeError("cached base image source revision does not match checkout")
    if (
        _digest_label(labels, PYTHON_RUNTIME_IDENTITY_LABEL)
        != python_runtime_identity_digest
    ):
        raise RuntimeError("cached base image Python runtime identity drifted")
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


def _image_runtime_identity_digest(identity: dict) -> str:
    """Return the concrete content identity of one Docker image."""

    image_id = identity.get("id")
    if (
        type(image_id) is not str
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id)
    ):
        raise RuntimeError("Docker image identity is not a content-addressed sha256")
    return image_id.removeprefix("sha256:")


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


def _verified_profile_image_identity(
    tag: str,
    *,
    profile_id: str,
    category_id: str,
    profile_revision: str,
    build_input_digest: str,
) -> dict:
    identity = _image_identity(tag)
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


def _category_current_tag(category_id: str) -> str:
    if PROFILE_TOKEN_RE.fullmatch(category_id) is None:
        raise ValueError("environment category id is not a deployment token")
    return f"noetrium-env-category-{category_id}:current"


def _publish_category_current_alias(
    tag: str,
    *,
    profile_id: str,
    category_id: str,
    profile_revision: str,
    build_input_digest: str,
    immutable_identity: dict,
) -> str:
    current_tag = _category_current_tag(category_id)
    _run(("docker", "tag", tag, current_tag))
    current_identity = _verified_profile_image_identity(
        current_tag,
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
    rebuild: bool = False,
    allow_draining: bool = False,
    allow_retired: bool = False,
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
    unknown_build_input_overrides = tuple(
        sorted(
            set(profile_build_input_overrides)
            - declared_build_input_variables
        )
    )
    if unknown_build_input_overrides:
        raise RuntimeError(
            "profile build input overrides are not declared by selected "
            f"profiles: {unknown_build_input_overrides!r}"
        )

    _run(("docker", "--version"))
    _run(("docker", "compose", "version"))

    work_root = work_root.resolve()
    scratch_root = work_root / "build"
    runtime_root = work_root / "runtime"
    shared_root = runtime_root / "shared"
    instances_root = runtime_root / "instances"
    shared_root.mkdir(parents=True, exist_ok=True)
    instances_root.mkdir(parents=True, exist_ok=True)
    shared_root.chmod(0o777)
    instances_root.chmod(0o777)

    python_source_identity = _ensure_image_identity(python_runtime_image)
    python_runtime_identity_digest = _image_runtime_identity_digest(
        python_source_identity
    )
    profile_input_image_cache: dict[str, dict] = {}

    base_tag = (
        f"noetrium:{source_sha}-{python_runtime_identity_digest}"
    )
    reused_base = _image_exists(base_tag) and not rebuild
    build_mode = "reused-verified-base" if reused_base else "qualified-distribution-build"

    if reused_base:
        scratch_root.mkdir(parents=True, exist_ok=True)
        base_identity = _image_identity(base_tag)
        wheel_sha256, distribution_evidence_sha256 = _cached_base_provenance(
            base_identity,
            source_sha,
            python_runtime_identity_digest,
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
                (
                    "PLATFORM_PYTHON_RUNTIME_IDENTITY_DIGEST="
                    f"{python_runtime_identity_digest}"
                ),
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
        built_wheel, built_distribution = _cached_base_provenance(
            base_identity,
            source_sha,
            python_runtime_identity_digest,
        )
        if (
            built_wheel != wheel_sha256
            or built_distribution != distribution_evidence_sha256
        ):
            raise RuntimeError("built base provenance labels drifted")

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
            "--expected-python-runtime-identity-digest",
            python_runtime_identity_digest,
            "--output",
            str(base_verification),
        )
    )

    base_identity["reused"] = reused_base
    base_identity["runtime_identity_digest"] = _image_runtime_identity_digest(
        base_identity
    )
    images: dict[str, dict] = {"base": base_identity}
    profile_build_inputs: dict[str, dict[str, object]] = {}
    for profile_id in profiles:
        row = by_id[profile_id]
        input_environment, resolved_build_inputs = (
            _resolve_profile_build_inputs(
                row,
                overrides=profile_build_input_overrides,
                image_identity_cache=profile_input_image_cache,
            )
        )
        profile_build_inputs[profile_id] = resolved_build_inputs
        if row.get("build_mode") == "base-only":
            _run(
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
            )
            profile_revision = _profile_revision(row)
            build_input_digest = _profile_build_input_digest(
                row,
                profile_revision=profile_revision,
                base_runtime_identity_digest=base_identity[
                    "runtime_identity_digest"
                ],
                resolved_build_inputs=resolved_build_inputs,
            )
            profile_identity = dict(base_identity)
            profile_identity["profile_id"] = profile_id
            profile_identity["profile_revision"] = profile_revision
            profile_identity["build_input_digest"] = build_input_digest
            profile_identity["lifecycle"] = row["lifecycle"]
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
        revision = _profile_revision(row)
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
        env["PLATFORM_IMAGE"] = base_tag
        env[image_env] = tag
        env.update(input_environment)
        env["PLATFORM_HOST_DATA_ROOT"] = str(runtime_root)
        qualification_instance = (
            instances_root
            / f"doctor-{profile_id}-{build_input_digest[:24]}"
        )
        _prepare_qualification_instance(
            qualification_instance,
            compose_path=ROOT / compose,
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
                *_qualification_label_args(),
                "platform-runtime",
                "environment-doctor",
                row["category_id"],
            ),
            env=env,
        )
        shutil.rmtree(qualification_instance)
        profile_identity = _verified_profile_image_identity(
            tag,
            profile_id=profile_id,
            category_id=row["category_id"],
            profile_revision=revision,
            build_input_digest=build_input_digest,
        )
        profile_identity["reused"] = reused_profile
        profile_identity["runtime_identity_digest"] = _image_runtime_identity_digest(
            profile_identity
        )
        profile_identity["profile_revision"] = revision
        profile_identity["build_input_digest"] = build_input_digest
        profile_identity["lifecycle"] = row["lifecycle"]
        profile_identity["qualification_instance_cleaned"] = True
        if row["lifecycle"] == "active" and row.get("default_for_category") is True:
            profile_identity["current_tag"] = _publish_category_current_alias(
                tag,
                profile_id=profile_id,
                category_id=row["category_id"],
                profile_revision=revision,
                build_input_digest=build_input_digest,
                immutable_identity=profile_identity,
            )
        images[profile_id] = profile_identity

    receipt = {
        "schema": "noetrium.environment-image-build.v4",
        "source_sha": source_sha,
        "branch": branch,
        "catalog_sha256": _sha256(CATALOG_PATH),
        "wheel_sha256": wheel_sha256,
        "distribution_evidence_sha256": distribution_evidence_sha256,
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
                "profile_revision": _profile_revision(by_id[profile_id]),
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
        build_environment_images(
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
            rebuild=args.rebuild,
            allow_draining=args.allow_draining,
            allow_retired=args.allow_retired,
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

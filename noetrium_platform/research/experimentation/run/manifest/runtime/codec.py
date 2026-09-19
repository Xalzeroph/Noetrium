from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from noetrium_platform.research.experimentation.identity import OptionalIdentityFacet, ReplayLevel
from ..api import CompositionPlanReference, RunLaunchManifest, RunResearchSemanticsReference


class RunLaunchManifestDecodeError(ValueError):
    """A launch-manifest document violates the frozen run contract."""


RUN_LAUNCH_MANIFEST_SCHEMA_VERSION = "5"
_WIRE_FIELDS = frozenset({"schema_version", "manifest"})
_FIELDS = frozenset(
    {
        "release_digest",
        "prompt_generation_digest",
        "prompt_promotion_digest",
        "role_model_manifest_digest",
        "qualified_deployment_digests",
        "target_host_identity_digest",
        "participant_implementation_inventory_digest",
        "participant_runtime_inventory_digest",
        "participant_binding_manifest_digest",
        "project_manifest_digest",
        "experiment_spec_digest",
        "research_semantics",
        "command_argv",
        "launcher_binary_sha256",
        "command_environment_digest",
        "config_digests",
        "seed_identity",
        "composition_plans",
    }
)
_RESEARCH_FIELDS = frozenset({"research_plan_digest", "study_plan_digest", "measurement_protocol_digest", "trial_protocol_digest", "method_implementation_digest", "intervention", "topology", "participant_schedule", "revision", "replay_level"})
_PLAN_FIELDS = frozenset(
    {"composition_id", "owner_key", "scope_key", "plan_digest"}
)


def encode_run_launch_manifest(manifest: RunLaunchManifest) -> bytes:
    document = {
        "schema_version": RUN_LAUNCH_MANIFEST_SCHEMA_VERSION,
        "manifest": asdict(manifest),
    }
    return json.dumps(
        document,
        sort_keys=True,
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8") + b"\n"


def _require_document(raw: bytes) -> dict[str, object]:
    if type(raw) is not bytes:
        raise TypeError("run launch manifest payload must be bytes")
    envelope = json.loads(raw.decode("utf-8"))
    if not isinstance(envelope, dict) or set(envelope) != _WIRE_FIELDS:
        raise TypeError("run launch manifest envelope fields are not exact")
    if type(envelope["schema_version"]) is not str or envelope["schema_version"] != RUN_LAUNCH_MANIFEST_SCHEMA_VERSION:
        raise TypeError("run launch manifest schema_version is unsupported")
    document = envelope["manifest"]
    if not isinstance(document, dict) or set(document) != _FIELDS:
        raise TypeError("run launch manifest fields are not exact")
    return document


def _require_string(document: dict[str, object], field: str) -> str:
    value = document[field]
    if type(value) is not str:
        raise TypeError(f"run launch manifest {field} must be a string")
    return value


def _require_string_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(type(item) is not str for item in value):
        raise TypeError(
            f"run launch manifest {field} must be a list of strings"
        )
    return tuple(value)



def _decode_facet(value: object, field: str) -> OptionalIdentityFacet:
    if not isinstance(value, dict) or set(value) != {"digest"}:
        raise TypeError(f"run launch manifest research_semantics {field} facet is not exact")
    digest = value["digest"]
    if digest is not None and type(digest) is not str:
        raise TypeError(f"run launch manifest research_semantics {field} digest must be string or null")
    return OptionalIdentityFacet(digest)


def _decode_research(value: object) -> RunResearchSemanticsReference:
    if not isinstance(value, dict) or set(value) != _RESEARCH_FIELDS:
        raise TypeError("run launch manifest research_semantics is not exact")
    required = ("research_plan_digest", "study_plan_digest", "measurement_protocol_digest", "trial_protocol_digest", "method_implementation_digest", "replay_level")
    if any(type(value[field]) is not str for field in required):
        raise TypeError("run launch manifest research_semantics scalar fields must be strings")
    return RunResearchSemanticsReference(
        research_plan_digest=value["research_plan_digest"],
        study_plan_digest=value["study_plan_digest"],
        measurement_protocol_digest=value["measurement_protocol_digest"],
        trial_protocol_digest=value["trial_protocol_digest"],
        method_implementation_digest=value["method_implementation_digest"],
        intervention=_decode_facet(value["intervention"], "intervention"),
        topology=_decode_facet(value["topology"], "topology"),
        participant_schedule=_decode_facet(value["participant_schedule"], "participant_schedule"),
        revision=_decode_facet(value["revision"], "revision"),
        replay_level=ReplayLevel(value["replay_level"]),
    )

def _decode_plan(row: object) -> CompositionPlanReference:
    if not isinstance(row, dict) or set(row) != _PLAN_FIELDS:
        raise TypeError("run launch manifest composition plan is not exact")
    values = {
        field: row[field]
        for field in ("composition_id", "owner_key", "scope_key", "plan_digest")
    }
    if any(type(value) is not str for value in values.values()):
        raise TypeError("run launch manifest composition plan fields must be strings")
    return CompositionPlanReference(**values)


def _decode_plans(value: object) -> tuple[CompositionPlanReference, ...]:
    if not isinstance(value, list):
        raise TypeError("run launch manifest composition_plans must be a list")
    return tuple(_decode_plan(row) for row in value)


def _decode_config_pair(row: object) -> tuple[str, str]:
    if not isinstance(row, list) or len(row) != 2:
        raise TypeError("run launch manifest config digest must be a pair")
    if any(type(item) is not str for item in row):
        raise TypeError("run launch manifest config digest values must be strings")
    return row[0], row[1]


def _decode_config(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list):
        raise TypeError("run launch manifest config_digests must be a list")
    return tuple(_decode_config_pair(row) for row in value)


def _build_manifest(document: dict[str, object]) -> RunLaunchManifest:
    return RunLaunchManifest(
        release_digest=_require_string(document, "release_digest"),
        prompt_generation_digest=_require_string(
            document, "prompt_generation_digest"
        ),
        prompt_promotion_digest=_require_string(
            document, "prompt_promotion_digest"
        ),
        role_model_manifest_digest=_require_string(
            document, "role_model_manifest_digest"
        ),
        qualified_deployment_digests=_require_string_list(
            document["qualified_deployment_digests"],
            "qualified_deployment_digests",
        ),
        target_host_identity_digest=_require_string(
            document, "target_host_identity_digest"
        ),
        participant_implementation_inventory_digest=_require_string(
            document, "participant_implementation_inventory_digest"
        ),
        participant_runtime_inventory_digest=_require_string(
            document, "participant_runtime_inventory_digest"
        ),
        participant_binding_manifest_digest=_require_string(
            document, "participant_binding_manifest_digest"
        ),
        project_manifest_digest=_require_string(document, "project_manifest_digest"),
        experiment_spec_digest=_require_string(document, "experiment_spec_digest"),
        research_semantics=_decode_research(document["research_semantics"]),
        command_argv=_require_string_list(document["command_argv"], "command_argv"),
        launcher_binary_sha256=_require_string(
            document, "launcher_binary_sha256"
        ),
        command_environment_digest=_require_string(
            document, "command_environment_digest"
        ),
        config_digests=_decode_config(document["config_digests"]),
        seed_identity=_require_string(document, "seed_identity"),
        composition_plans=_decode_plans(document["composition_plans"]),
    )


def decode_run_launch_manifest(raw: bytes) -> RunLaunchManifest:
    try:
        manifest = _build_manifest(_require_document(raw))
        if raw != encode_run_launch_manifest(manifest):
            raise ValueError("run launch manifest bytes are not canonical")
        return manifest
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
        AttributeError,
    ) as exc:
        raise RunLaunchManifestDecodeError(
            "run launch manifest violates the frozen run contract"
        ) from exc


def load_run_launch_manifest(path: str | Path) -> RunLaunchManifest:
    manifest_path = Path(path).expanduser().resolve()
    if not manifest_path.is_file():
        raise RunLaunchManifestDecodeError(
            f"run launch manifest is not a regular file: {manifest_path}"
        )
    try:
        return decode_run_launch_manifest(manifest_path.read_bytes())
    except OSError as exc:
        raise RunLaunchManifestDecodeError(
            f"run launch manifest cannot be read: {manifest_path}"
        ) from exc


__all__ = [
    "RUN_LAUNCH_MANIFEST_SCHEMA_VERSION",
    "RunLaunchManifestDecodeError",
    "decode_run_launch_manifest",
    "encode_run_launch_manifest",
    "load_run_launch_manifest",
]

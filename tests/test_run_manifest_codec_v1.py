from __future__ import annotations

import json

import pytest

from tests_support import frozen_runtime_manifest
from noetrium_platform.research.experimentation.run.manifest.runtime import (
    RunLaunchManifestDecodeError,
    decode_run_launch_manifest,
    encode_run_launch_manifest,
)


def test_run_launch_manifest_codec_round_trips_the_frozen_identity() -> None:
    manifest = frozen_runtime_manifest(
        release_digest="r",
        command_argv=("/opt/example/envs/project/bin/python", "-m", "runner"),
    )
    decoded = decode_run_launch_manifest(encode_run_launch_manifest(manifest))
    assert decoded == manifest
    assert decoded.digest() == manifest.digest()


def test_run_launch_manifest_codec_rejects_semantically_equivalent_noncanonical_bytes() -> None:
    encoded = encode_run_launch_manifest(frozen_runtime_manifest())
    document = json.loads(encoded)
    noncanonical = json.dumps(document, sort_keys=False, separators=(",", ":")).encode("utf-8")
    assert noncanonical != encoded
    with pytest.raises(RunLaunchManifestDecodeError):
        decode_run_launch_manifest(noncanonical)


def test_run_launch_manifest_codec_rejects_unknown_or_missing_fields() -> None:
    raw = json.loads(encode_run_launch_manifest(frozen_runtime_manifest()))
    raw["unexpected"] = "drift"
    with pytest.raises(RunLaunchManifestDecodeError):
        decode_run_launch_manifest(json.dumps(raw).encode())

    raw = json.loads(encode_run_launch_manifest(frozen_runtime_manifest()))
    del raw["manifest"]["seed_identity"]
    with pytest.raises(RunLaunchManifestDecodeError):
        decode_run_launch_manifest(json.dumps(raw).encode())


def test_run_launch_manifest_codec_rejects_unsupported_or_untyped_wire_version() -> None:
    for version in ("1", "2", "3", "4", "6", 5, True, None):
        raw = json.loads(encode_run_launch_manifest(frozen_runtime_manifest()))
        raw["schema_version"] = version
        with pytest.raises(RunLaunchManifestDecodeError):
            decode_run_launch_manifest(json.dumps(raw).encode())


@pytest.mark.parametrize(
    "field",
    (
        "release_digest",
        "prompt_generation_digest",
        "target_host_identity_digest",
        "experiment_spec_digest",
        "seed_identity",
    ),
)
def test_run_launch_manifest_codec_rejects_scalar_string_coercion(field) -> None:
    raw = json.loads(encode_run_launch_manifest(frozen_runtime_manifest()))
    raw["manifest"][field] = 7
    with pytest.raises(RunLaunchManifestDecodeError):
        decode_run_launch_manifest(json.dumps(raw).encode())


def test_run_launch_manifest_codec_rejects_malformed_nested_identity() -> None:
    raw = json.loads(encode_run_launch_manifest(frozen_runtime_manifest()))
    raw["manifest"]["composition_plans"][0]["owner_key"] = False
    with pytest.raises(RunLaunchManifestDecodeError):
        decode_run_launch_manifest(json.dumps(raw).encode())


def test_run_launch_manifest_codec_rejects_research_semantics_drift() -> None:
    raw = json.loads(encode_run_launch_manifest(frozen_runtime_manifest()))
    raw["manifest"]["research_semantics"]["replay_level"] = "unknown"
    with pytest.raises(RunLaunchManifestDecodeError):
        decode_run_launch_manifest(json.dumps(raw).encode())

    raw = json.loads(encode_run_launch_manifest(frozen_runtime_manifest()))
    del raw["manifest"]["research_semantics"]["revision"]
    with pytest.raises(RunLaunchManifestDecodeError):
        decode_run_launch_manifest(json.dumps(raw).encode())


def test_run_launch_manifest_codec_rejects_malformed_optional_identity_facet() -> None:
    raw = json.loads(encode_run_launch_manifest(frozen_runtime_manifest()))
    raw["manifest"]["research_semantics"]["revision"] = {"digest": 7}
    with pytest.raises(RunLaunchManifestDecodeError):
        decode_run_launch_manifest(json.dumps(raw).encode())

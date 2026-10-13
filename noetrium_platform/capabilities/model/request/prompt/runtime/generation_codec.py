from __future__ import annotations

from dataclasses import dataclass
import json

from noetrium_platform.foundation.kernel.kernel import JsonObject, freeze_json
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.unit_codec import decode_unit, encode_unit
from noetrium_platform.capabilities.model.request.prompt.api.unit_semantics import (
    compile_prompt_text,
    output_schema_digest,
    output_schema_id,
    prompt_bundle_digest,
    prompt_id,
    prompt_max_output_tokens,
    prompt_model_family,
    prompt_output_schema_id,
    prompt_role,
    prompt_temperature,
    prompt_top_p,
    prompt_version,
    require_output_schema,
    require_prompt_unit,
)
from .blocks import PromptBlockPolicy
from .publication_common import PromptPublicationError, sha256_bytes
from .runtime import ActivePromptBundle
from .schema import OutputSchemaRegistry


@dataclass(frozen=True, slots=True)
class EncodedGeneration:
    generation_id: str
    payload: JsonObject
    payload_sha256: str
    envelope_bytes: bytes
    bundle_digests: tuple[tuple[str, str], ...]
    policy_digests: tuple[tuple[str, str], ...]
    schema_digests: tuple[tuple[str, str], ...]


def policy_digest(policy: PromptBlockPolicy) -> str:
    payload = {
        "role": policy.role,
        "required": sorted(x.value for x in policy.required),
        "allowed": sorted(x.value for x in policy.allowed),
        "max_chars": sorted((k.value, v) for k, v in policy.max_chars_by_kind),
    }
    return sha256_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    )

def _bundle_payload(spec: NoetriumUnit, schema: NoetriumUnit) -> dict[str, object]:
    spec = require_prompt_unit(spec)
    schema = require_output_schema(schema)
    if output_schema_id(schema) != prompt_output_schema_id(spec):
        raise ValueError("prompt output schema identity drift")
    return {
        "prompt_id": prompt_id(spec),
        "role": prompt_role(spec),
        "version": prompt_version(spec),
        "text": compile_prompt_text(spec),
        "digest": prompt_bundle_digest(spec),
        "output_schema": prompt_output_schema_id(spec),
        "schema_digest": output_schema_digest(schema),
        "model_family": prompt_model_family(spec),
        "temperature": prompt_temperature(spec),
        "top_p": prompt_top_p(spec),
        "max_output_tokens": prompt_max_output_tokens(spec),
        "prompt_unit_hex": encode_unit(spec).hex(),
        "schema_unit_hex": encode_unit(schema).hex(),
    }


def encode_generation(
    generation_id: str,
    specs: tuple[NoetriumUnit, ...],
    policies: dict[str, PromptBlockPolicy],
    schemas: OutputSchemaRegistry,
) -> EncodedGeneration:
    bundles = []
    bundle_digests = []
    policy_digests = []
    schema_digests = []
    for spec in sorted(specs, key=prompt_id):
        spec = require_prompt_unit(spec)
        schema = schemas.require(prompt_output_schema_id(spec))
        role = prompt_role(spec)
        policy = policies[role]
        bundle = _bundle_payload(spec, schema)
        bundles.append(bundle)
        bundle_digests.append((prompt_id(spec), prompt_bundle_digest(spec)))
        policy_digests.append((role, policy_digest(policy)))
        schema_digests.append((output_schema_id(schema), output_schema_digest(schema)))
    pd = tuple(sorted(set(policy_digests)))
    sd = tuple(sorted(set(schema_digests)))
    bd = tuple(bundle_digests)
    body = {
        "generation_id": generation_id,
        "bundles": bundles,
        "bundle_digests": bd,
        "policy_digests": pd,
        "schema_digests": sd,
    }
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    digest = sha256_bytes(encoded)
    envelope = json.dumps(
        {"payload_sha256": digest, "payload": body},
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ).encode()
    return EncodedGeneration(
        generation_id,
        freeze_json(body),
        digest,
        envelope,
        bd,
        pd,
        sd,
    )


def _decode_unit_hex(value: object, *, field: str) -> NoetriumUnit:
    if type(value) is not str or not value:
        raise PromptPublicationError(f"{field} is missing")
    try:
        return decode_unit(bytes.fromhex(value))
    except (TypeError, ValueError) as exc:
        raise PromptPublicationError(f"{field} is invalid") from exc


def decode_generation(
    raw: str,
    generation_id: str,
) -> tuple[str, tuple[ActivePromptBundle, ...], JsonObject]:
    envelope = json.loads(raw)
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise PromptPublicationError("invalid generation payload")
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    digest = sha256_bytes(encoded)
    if digest != envelope.get("payload_sha256"):
        raise PromptPublicationError("prompt generation hash mismatch")
    if payload.get("generation_id") != generation_id:
        raise PromptPublicationError("generation identity mismatch")

    bundles = []
    for bundle in payload["bundles"]:
        if not isinstance(bundle, dict):
            raise PromptPublicationError("prompt bundle payload is invalid")
        prompt = require_prompt_unit(
            _decode_unit_hex(bundle.get("prompt_unit_hex"), field="prompt Unit")
        )
        schema = require_output_schema(
            _decode_unit_hex(bundle.get("schema_unit_hex"), field="schema Unit")
        )
        if prompt_bundle_digest(prompt) != bundle.get("digest"):
            raise PromptPublicationError(
                f"prompt Unit digest mismatch: {prompt_id(prompt)}"
            )
        if output_schema_digest(schema) != bundle.get("schema_digest"):
            raise PromptPublicationError(
                f"output schema Unit digest mismatch: {output_schema_id(schema)}"
            )
        expected = _bundle_payload(prompt, schema)
        if expected != bundle:
            raise PromptPublicationError(
                f"prompt bundle semantic drift: {prompt_id(prompt)}"
            )
        bundles.append(
            ActivePromptBundle(
                prompt_id(prompt),
                prompt_role(prompt),
                prompt_version(prompt),
                prompt_bundle_digest(prompt),
                compile_prompt_text(prompt),
                prompt_output_schema_id(prompt),
                prompt_model_family(prompt),
                prompt_temperature(prompt),
                prompt_top_p(prompt),
                prompt_max_output_tokens(prompt),
            )
        )
    return digest, tuple(bundles), freeze_json(payload)

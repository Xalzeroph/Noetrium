from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from collections.abc import Mapping

from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity, JsonInput, canonical_bytes
from .compile_pipeline import PromptCompilationReceipt
from .runtime_contracts import PromptResolution


@dataclass(frozen=True, slots=True)
class PromptExecutionContract:
    request_id: str
    generation_id: str
    bundle_digest: str
    dynamic_digest: str
    schema_digest: str
    model_resume_key: tuple[object,...]
    compiled_text_sha256: str
    request_body_sha256: str
    compiled_chars: int
    compiled_bytes: int
    block_stats_digest: str


def build_execution_contract(
    *,
    request_id: str,
    compilation: PromptCompilationReceipt,
    resolution: PromptResolution,
    model: ImmutableModelIdentity,
    request_body: Mapping[str, JsonInput],
) -> PromptExecutionContract:
    if compilation.generation_id != resolution.generation_id:
        raise ValueError("prompt execution generation drift")
    if compilation.prompt_id != resolution.bundle.prompt_id:
        raise ValueError("prompt execution prompt identity drift")
    if compilation.bundle_digest != resolution.bundle.digest:
        raise ValueError("prompt execution bundle digest drift")

    compiled = compilation.compiled
    body = canonical_bytes(request_body)
    stats = json.dumps(
        [
            {
                "kind": x.kind,
                "chars": x.chars,
                "bytes": x.bytes,
                "source_digest": x.source_digest,
            }
            for x in compiled.block_stats
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return PromptExecutionContract(
        request_id,
        compilation.generation_id,
        compilation.bundle_digest,
        compiled.dynamic_digest,
        compilation.schema_digest,
        model.resume_key(),
        hashlib.sha256(compiled.text.encode()).hexdigest(),
        hashlib.sha256(body).hexdigest(),
        compiled.compiled_chars,
        compiled.compiled_bytes,
        hashlib.sha256(stats).hexdigest(),
    )

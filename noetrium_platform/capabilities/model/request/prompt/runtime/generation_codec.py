from __future__ import annotations
from dataclasses import dataclass
import json

from noetrium_platform.foundation.kernel.kernel import JsonObject, freeze_json


from .blocks import PromptBlockPolicy
from .publication_common import PromptPublicationError, sha256_bytes
from .runtime import ActivePromptBundle
from .schema import OutputSchemaRegistry
from .spec import PromptSpec

@dataclass(frozen=True, slots=True)
class EncodedGeneration:
    generation_id: str
    payload: JsonObject
    payload_sha256: str
    envelope_bytes: bytes
    bundle_digests: tuple[tuple[str,str],...]
    policy_digests: tuple[tuple[str,str],...]
    schema_digests: tuple[tuple[str,str],...]

def policy_digest(policy:PromptBlockPolicy)->str:
    payload={"role":policy.role,"required":sorted(x.value for x in policy.required),"allowed":sorted(x.value for x in policy.allowed),"max_chars":sorted((k.value,v) for k,v in policy.max_chars_by_kind)}
    return sha256_bytes(json.dumps(payload,sort_keys=True,separators=(",",":")).encode())

def encode_generation(generation_id:str,specs:tuple[PromptSpec,...],policies:dict[str,PromptBlockPolicy],schemas:OutputSchemaRegistry)->EncodedGeneration:
    bundles=[]; bundle_digests=[]; policy_digests=[]; schema_digests=[]
    for spec in sorted(specs,key=lambda x:x.prompt_id):
        schema=schemas.require(spec.output_schema); policy=policies[spec.role]; digest=spec.bundle_digest()
        bundles.append({"prompt_id":spec.prompt_id,"role":spec.role,"version":spec.version,"text":spec.compile(),"digest":digest,"output_schema":spec.output_schema,"schema_digest":schema.digest(),"model_family":spec.model_family,"temperature":spec.temperature,"top_p":spec.top_p,"max_output_tokens":spec.max_output_tokens})
        bundle_digests.append((spec.prompt_id,digest)); policy_digests.append((spec.role,policy_digest(policy))); schema_digests.append((schema.schema_id,schema.digest()))
    pd=tuple(sorted(set(policy_digests))); sd=tuple(sorted(set(schema_digests))); bd=tuple(bundle_digests)
    body={"generation_id":generation_id,"bundles":bundles,"bundle_digests":bd,"policy_digests":pd,"schema_digests":sd}
    encoded=json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode(); digest=sha256_bytes(encoded)
    envelope=json.dumps({"payload_sha256":digest,"payload":body},ensure_ascii=False,sort_keys=True,indent=2).encode()
    return EncodedGeneration(generation_id,freeze_json(body),digest,envelope,bd,pd,sd)

def decode_generation(raw:str,generation_id:str)->tuple[str,tuple[ActivePromptBundle,...],JsonObject]:
    envelope=json.loads(raw); payload=envelope.get("payload")
    if not isinstance(payload,dict): raise PromptPublicationError("invalid generation payload")
    encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode(); digest=sha256_bytes(encoded)
    if digest!=envelope.get("payload_sha256"): raise PromptPublicationError("prompt generation hash mismatch")
    if payload.get("generation_id")!=generation_id: raise PromptPublicationError("generation identity mismatch")
    bundles=[]
    for bundle in payload["bundles"]:
        check={"prompt_id":bundle["prompt_id"],"role":bundle["role"],"version":bundle["version"],"model_family":bundle["model_family"],"output_schema":bundle["output_schema"],"temperature":bundle["temperature"],"top_p":bundle["top_p"],"max_output_tokens":bundle["max_output_tokens"],"text":bundle["text"]}
        actual=sha256_bytes(json.dumps(check,sort_keys=True,ensure_ascii=False).encode())
        if actual!=bundle["digest"]: raise PromptPublicationError(f"bundle hash mismatch: {bundle['prompt_id']}")
        bundles.append(ActivePromptBundle(bundle["prompt_id"],bundle["role"],bundle["version"],bundle["digest"],bundle["text"],bundle["output_schema"],bundle["model_family"],bundle["temperature"],bundle["top_p"],bundle["max_output_tokens"]))
    return digest,tuple(bundles),freeze_json(payload)

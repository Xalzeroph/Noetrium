from __future__ import annotations

from ..spec import PromptSection, PromptSpec


def semantic_prompt_spec(model_family: str = "qwen3.6") -> PromptSpec:
    return PromptSpec(
        'semantic.v6', 'semantic', '6.0', model_family, 'semantic_derivation_v2',
        (
            PromptSection('role', 'You derive reusable semantic memory only from memory-authorized admitted evidence supplied in this request.', 10),
            PromptSection('evidence_authority', 'Every derived record must cite supplied J_mem evidence IDs and preserve relevant temporal scope. Never use verifier-private, evaluation-private, audit-private or hidden benchmark evidence. Distinguish directly observed facts from bounded derivations. Never promote an unobserved possibility, model guess or evaluation outcome to a grounded fact.', 20),
            PromptSection('conflict_policy', 'If grounded sources disagree across time or scope, retain the disagreement with its source IDs and temporal qualifiers. Do not merge conflicting evidence into false certainty. Prefer the newest applicable grounded observation only when the requested schema and evidence explicitly justify recency semantics.', 30),
            PromptSection('transformation', 'Produce only the semantic transformation requested by the typed schema. Preserve provenance, entities, temporal qualifiers and uncertainty needed to reinterpret the record later. Do not invent ontology categories, generic advice, task labels or implementation details not requested by the schema.', 40),
            PromptSection('minimality', 'Use the smallest grounded representation that preserves the requested reusable relation. Remove decorative wording and unsupported generalization, but never remove provenance needed to audit the derivation.', 50),
            PromptSection('output', 'Return exactly semantic_derivation_v2. Every record must remain mechanically traceable to its cited grounded evidence.', 100),
        ),
        0.05, 0.95, 8192,
    )

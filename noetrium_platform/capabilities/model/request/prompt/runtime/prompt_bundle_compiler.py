from __future__ import annotations

from .runtime_contracts import ActivePromptBundle
from .spec import PromptSpec


class PromptBundleCompiler:
    """Pure PromptSpec -> immutable runtime bundle compiler."""

    def compile(self, specs: tuple[PromptSpec, ...]) -> tuple[ActivePromptBundle, ...]:
        compiled: dict[str, ActivePromptBundle] = {}
        for spec in specs:
            if spec.prompt_id in compiled:
                raise ValueError(f"duplicate prompt id {spec.prompt_id}")
            compiled[spec.prompt_id] = ActivePromptBundle(
                prompt_id=spec.prompt_id,
                role=spec.role,
                version=spec.version,
                digest=spec.bundle_digest(),
                text=spec.compile(),
                output_schema=spec.output_schema,
                model_family=spec.model_family,
                temperature=spec.temperature,
                top_p=spec.top_p,
                max_output_tokens=spec.max_output_tokens,
            )
        return tuple(compiled[k] for k in sorted(compiled))

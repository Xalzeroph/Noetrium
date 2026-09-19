from __future__ import annotations

from pathlib import Path

from noetrium_platform.composition.prompt_registry import build_durable_prompt_registry


def make_prompt_registry(root: Path):
    return build_durable_prompt_registry(
        generations_root=root / "generations",
        promotion_records_root=root / "promotions",
        active_pointer_path=root / "ACTIVE",
        publication_lock_path=root / ".publication.lock",
    )


__all__ = ["make_prompt_registry"]

from __future__ import annotations

from noetrium_platform.foundation.governance.release.runtime.pipeline import ReleasePipeline


def build_release_pipeline() -> ReleasePipeline:
    """Bind release runtime to platform-owned quality evidence providers."""

    return ReleasePipeline()


__all__ = ["build_release_pipeline"]

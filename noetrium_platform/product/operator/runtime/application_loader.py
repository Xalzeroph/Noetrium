from __future__ import annotations

from dataclasses import dataclass
import importlib
from pathlib import Path

from noetrium_platform.product.operator.api import ResearchApplicationPort


@dataclass(frozen=True, slots=True)
class ResearchApplicationFactorySpec:
    module: str
    attribute: str

    @classmethod
    def parse(cls, value: str) -> "ResearchApplicationFactorySpec":
        module, separator, attribute = value.partition(":")
        if not separator or not module.strip() or not attribute.strip():
            raise ValueError("application factory must be MODULE:ATTRIBUTE")
        if ":" in attribute:
            raise ValueError("application factory must contain exactly one ':'")
        return cls(module.strip(), attribute.strip())


def load_research_application(
    spec: ResearchApplicationFactorySpec,
    *,
    config_path: Path | None = None,
) -> ResearchApplicationPort:
    try:
        module = importlib.import_module(spec.module)
    except ImportError as exc:
        raise ValueError(f"cannot import research application module: {spec.module}") from exc
    try:
        factory = getattr(module, spec.attribute)
    except AttributeError as exc:
        raise ValueError(
            f"research application factory is missing: {spec.module}:{spec.attribute}"
        ) from exc
    if not callable(factory):
        raise ValueError("research application factory must be callable")
    application = factory(config_path)
    if not callable(getattr(application, "execute", None)):
        raise TypeError("research application factory returned an invalid application")
    return application


__all__ = [
    "ResearchApplicationFactorySpec",
    "load_research_application",
]

"""Composition adapters for the prompt API; projects must not import these."""

from .binding import FrozenPromptRequestBinding
from .selection import RegistryPromptSelection

__all__ = ["FrozenPromptRequestBinding", "RegistryPromptSelection"]

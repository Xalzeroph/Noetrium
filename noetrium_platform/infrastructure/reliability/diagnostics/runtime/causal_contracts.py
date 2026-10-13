from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import JsonScalar


class _FrozenAttributes(dict[str, JsonScalar]):
    """JSON-scalar mapping that preserves ordinary dict serialization."""

    @staticmethod
    def _immutable(*_args: object, **_kwargs: object) -> None:
        raise TypeError("causal snapshot attributes are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def freeze_causal_attributes(attrs: Mapping[str, JsonScalar]) -> Mapping[str, JsonScalar]:
    frozen: dict[str, JsonScalar] = {}
    for key, value in attrs.items():
        if not isinstance(key, str):
            raise TypeError("causal attribute keys must be strings")
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise TypeError(f"causal attribute {key!r} must be a JSON scalar")
        frozen[key] = value
    return _FrozenAttributes(frozen)

@dataclass(frozen=True, slots=True)
class CausalNodeSnapshot:
    node_id: str
    kind: str
    attrs: Mapping[str, JsonScalar]

    def __post_init__(self) -> None:
        if not self.node_id:
            raise ValueError("causal node_id cannot be empty")
        if not self.kind:
            raise ValueError("causal node kind cannot be empty")
        object.__setattr__(self, "attrs", freeze_causal_attributes(self.attrs))


@dataclass(frozen=True, slots=True)
class CausalEdge:
    source: str
    relation: str
    target: str

    def __post_init__(self) -> None:
        if not self.source or not self.relation or not self.target:
            raise ValueError("causal edges require source, relation and target")


@dataclass(frozen=True, slots=True)
class CausalGraphSnapshot:
    root_id: str
    nodes: tuple[CausalNodeSnapshot, ...]
    edges: tuple[CausalEdge, ...]

    def __post_init__(self) -> None:
        node_ids = tuple(node.node_id for node in self.nodes)
        if not self.root_id or self.root_id not in node_ids:
            raise ValueError("causal graph root must reference a snapshot node")
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("causal graph node identifiers must be unique")
        known = set(node_ids)
        if any(edge.source not in known or edge.target not in known for edge in self.edges):
            raise ValueError("causal graph edge references an unknown snapshot node")


__all__ = [
    "CausalEdge",
    "CausalGraphSnapshot",
    "CausalNodeSnapshot",
    "freeze_causal_attributes",
]
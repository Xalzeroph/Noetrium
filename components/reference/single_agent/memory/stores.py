"""Reusable working, episodic and vector memory components."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from threading import RLock
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from .persistence import MemoryPersistencePort

from noetrium.contracts.json import JsonValue, canonical_digest, freeze_json


@dataclass(frozen=True, slots=True)
class MemoryItem:
    memory_id: str
    content: str
    tags: tuple[str, ...] = ()
    embedding: tuple[float, ...] | None = None
    metadata: tuple[tuple[str, JsonValue], ...] = ()
    namespace: str = "default"
    item_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.memory_id) is not str or not self.memory_id.strip():
            raise ValueError("memory_id must be non-empty")
        if type(self.namespace) is not str or not self.namespace.strip():
            raise ValueError("memory namespace must be non-empty")
        if type(self.content) is not str:
            raise TypeError("memory content must be string")
        if type(self.tags) is not tuple or any(type(tag) is not str or not tag.strip() for tag in self.tags):
            raise TypeError("memory tags must contain non-empty strings")
        if len(self.tags) != len(set(self.tags)):
            raise ValueError("memory tags must be unique")
        if self.embedding is not None:
            if type(self.embedding) is not tuple or not self.embedding:
                raise ValueError("memory embedding must be a non-empty tuple")
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in self.embedding):
                raise ValueError("memory embedding must contain finite numbers")
        if type(self.metadata) is not tuple or any(type(row) is not tuple or len(row) != 2 for row in self.metadata):
            raise TypeError("memory metadata must be key/value tuples")
        normalized_metadata = []
        for key, value in self.metadata:
            if type(key) is not str or not key.strip():
                raise ValueError("memory metadata keys must be non-empty strings")
            normalized_metadata.append((key, freeze_json(value)))
        keys = [key for key, _value in normalized_metadata]
        if len(keys) != len(set(keys)):
            raise ValueError("memory metadata keys must be unique")
        object.__setattr__(self, "metadata", tuple(sorted(normalized_metadata)))
        object.__setattr__(self, "item_digest", canonical_digest({"namespace": self.namespace, "memory_id": self.memory_id, "content": self.content, "tags": self.tags, "embedding": self.embedding, "metadata": self.metadata}))

class WorkingMemory:
    """Bounded recency memory; state is immutable at every returned boundary."""

    def __init__(
        self,
        *,
        capacity: int = 32,
        persistence: "MemoryPersistencePort | None" = None,
    ) -> None:
        if type(capacity) is not int or capacity <= 0:
            raise ValueError("working memory capacity must be positive")
        self._capacity = capacity
        self._persistence = persistence
        loaded = () if persistence is None else persistence.load("working")
        self._items: tuple[MemoryItem, ...] = tuple(loaded[-capacity:])
        self._lock = RLock()

    @property
    def capacity(self) -> int:
        return self._capacity

    def remember(self, item: MemoryItem) -> tuple[MemoryItem, ...]:
        if type(item) is not MemoryItem:
            raise TypeError("working memory accepts MemoryItem")
        with self._lock:
            retained = tuple(
                row for row in self._items
                if (row.namespace, row.memory_id) != (item.namespace, item.memory_id)
            )
            self._items = (retained + (item,))[-self._capacity:]
            if self._persistence is not None:
                self._persistence.replace("working", self._items)
            return self._items

    def items(self) -> tuple[MemoryItem, ...]:
        with self._lock:
            return self._items


class EpisodicMemoryStore:
    """Thread-safe append/upsert store with deterministic lexical retrieval."""

    def __init__(self, *, persistence: "MemoryPersistencePort | None" = None) -> None:
        self._persistence = persistence
        self._items: dict[tuple[str, str], MemoryItem] = {
            (item.namespace, item.memory_id): item
            for item in (() if persistence is None else persistence.load("episodic"))
        }
        self._lock = RLock()

    def put(self, item: MemoryItem) -> MemoryItem:
        if type(item) is not MemoryItem:
            raise TypeError("episodic memory accepts MemoryItem")
        with self._lock:
            key = (item.namespace, item.memory_id)
            previous = self._items.get(key)
            if previous is not None and previous.item_digest != item.item_digest:
                raise ValueError("episodic memory identity collision")
            self._items[key] = item
            if self._persistence is not None:
                self._persistence.upsert("episodic", item)
            return item

    def items(self) -> tuple[MemoryItem, ...]:
        with self._lock:
            return tuple(sorted(self._items.values(), key=lambda row: (row.namespace, row.memory_id)))

    def get(self, memory_id: str, *, namespace: str = "default") -> MemoryItem:
        if type(memory_id) is not str or not memory_id.strip():
            raise ValueError("episodic memory memory_id must be non-empty")
        if type(namespace) is not str or not namespace.strip():
            raise ValueError("episodic memory namespace must be non-empty")
        with self._lock:
            return self._items[(namespace, memory_id)]

    def search(
        self, query: str, *, limit: int = 10, namespace: str | None = None
    ) -> tuple[MemoryItem, ...]:
        if type(query) is not str or not query.strip():
            raise ValueError("episodic memory query must be non-empty")
        if type(limit) is not int or not 1 <= limit <= 10_000:
            raise ValueError("episodic memory limit must be in [1, 10000]")
        if namespace is not None and (type(namespace) is not str or not namespace.strip()):
            raise ValueError("episodic memory namespace must be non-empty when present")
        needle = query.casefold()
        with self._lock:
            matches = tuple(
                item for item in self._items.values()
                if (namespace is None or item.namespace == namespace)
                and (needle in item.content.casefold() or any(needle in tag.casefold() for tag in item.tags))
            )
        return tuple(sorted(matches, key=lambda row: row.memory_id)[:limit])

class VectorMemoryStore:
    """Dependency-free deterministic vector retrieval with replace-by-identity."""

    def __init__(
        self,
        *,
        dimension: int,
        persistence: "MemoryPersistencePort | None" = None,
    ) -> None:
        if type(dimension) is not int or dimension <= 0:
            raise ValueError("vector memory dimension must be positive")
        self._dimension = dimension
        self._persistence = persistence
        self._items: dict[tuple[str, str], MemoryItem] = {}
        self._norms: dict[tuple[str, str], float] = {}
        for item in (() if persistence is None else persistence.load("vector")):
            if item.embedding is None or len(item.embedding) != dimension:
                raise ValueError("persisted vector memory embedding dimension mismatch")
            key = (item.namespace, item.memory_id)
            self._items[key] = item
            self._norms[key] = math.sqrt(sum(float(value) ** 2 for value in item.embedding))
        self._lock = RLock()

    @property
    def dimension(self) -> int:
        return self._dimension

    def upsert(self, item: MemoryItem) -> MemoryItem:
        if type(item) is not MemoryItem or item.embedding is None:
            raise TypeError("vector memory requires a MemoryItem with embedding")
        if len(item.embedding) != self._dimension:
            raise ValueError("vector memory embedding dimension mismatch")
        with self._lock:
            key = (item.namespace, item.memory_id)
            previous = self._items.get(key)
            if previous is not None and previous.item_digest != item.item_digest:
                raise ValueError("vector memory identity collision")
            self._items[key] = item
            self._norms[key] = math.sqrt(sum(float(value) ** 2 for value in item.embedding))
            if self._persistence is not None:
                self._persistence.upsert("vector", item)
            return item

    def upsert_text(
        self,
        memory_id: str,
        content: str,
        *,
        embedder: MemoryEmbedderPort,
        tags: tuple[str, ...] = (),
        metadata: tuple[tuple[str, JsonValue], ...] = (),
        namespace: str = "default",
    ) -> MemoryItem:
        embedding = embedder.embed(content)
        item = MemoryItem(memory_id, content, tags, tuple(embedding), metadata, namespace)
        return self.upsert(item)

    def items(self) -> tuple[MemoryItem, ...]:
        with self._lock:
            return tuple(sorted(self._items.values(), key=lambda row: (row.namespace, row.memory_id)))

    def search(
        self,
        query: tuple[float, ...],
        *,
        limit: int = 10,
        namespace: str | None = None,
    ) -> tuple[tuple[MemoryItem, float], ...]:
        if type(query) is not tuple or len(query) != self._dimension:
            raise ValueError("vector memory query dimension mismatch")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in query):
            raise ValueError("vector memory query must contain finite numbers")
        if type(limit) is not int or not 1 <= limit <= 10_000:
            raise ValueError("vector memory limit must be in [1, 10000]")
        if namespace is not None and (type(namespace) is not str or not namespace.strip()):
            raise ValueError("vector memory namespace must be non-empty when present")
        norm = math.sqrt(sum(float(value) ** 2 for value in query))
        if norm == 0:
            raise ValueError("vector memory query cannot be zero")
        with self._lock:
            scored = []
            for item in self._items.values():
                if namespace is not None and item.namespace != namespace:
                    continue
                assert item.embedding is not None
                item_norm = self._norms[(item.namespace, item.memory_id)]
                score = 0.0 if item_norm == 0 else sum(float(a) * float(b) for a, b in zip(query, item.embedding)) / (norm * item_norm)
                scored.append((item, score))
        return tuple(sorted(scored, key=lambda row: (-row[1], row[0].memory_id))[:limit])


class MemoryEmbedderPort(Protocol):
    def embed(self, text: str) -> tuple[float, ...]: ...


__all__ = ["EpisodicMemoryStore", "MemoryEmbedderPort", "MemoryItem", "VectorMemoryStore", "WorkingMemory"]

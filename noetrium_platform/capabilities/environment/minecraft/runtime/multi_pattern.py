from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SubstringAggregatePlan:
    """Compiled case-insensitive multi-pattern matcher for inventory aggregation.

    The automaton is Aho-Corasick: build O(total pattern characters), scan
    O(total key characters + matches).  A value contributes at most once per
    requested pattern for each inventory key, preserving ``substring in key``
    semantics even when a pattern occurs repeatedly in the same key.
    """

    originals_by_pattern: Mapping[str, tuple[str, ...]]
    transitions: tuple[Mapping[str, int], ...]
    failures: tuple[int, ...]
    outputs: tuple[tuple[str, ...], ...]
    empty_pattern_originals: tuple[str, ...]

    @classmethod
    def compile(cls, patterns: Iterable[str]) -> "SubstringAggregatePlan":
        """Compile the requested patterns into a sparse failure automaton.

        Algorithm-Complexity: O(N)
        Algorithm-Rationale: N is total pattern characters plus failure/output propagation work; nested loops traverse hierarchical characters and trie edges rather than a Cartesian product.
        """
        originals: dict[str, list[str]] = {}
        for original in patterns:
            normalized = original.lower()
            originals.setdefault(normalized, []).append(original)

        transitions: list[dict[str, int]] = [{}]
        failures: list[int] = [0]
        outputs: list[set[str]] = [set()]
        for pattern in originals:
            if not pattern:
                continue
            state = 0
            for char in pattern:
                next_state = transitions[state].get(char)
                if next_state is None:
                    next_state = len(transitions)
                    transitions[state][char] = next_state
                    transitions.append({})
                    failures.append(0)
                    outputs.append(set())
                state = next_state
            outputs[state].add(pattern)

        queue: deque[int] = deque(transitions[0].values())
        while queue:
            state = queue.popleft()
            for char, next_state in transitions[state].items():
                queue.append(next_state)
                fallback = failures[state]
                while fallback and char not in transitions[fallback]:
                    fallback = failures[fallback]
                failures[next_state] = transitions[fallback].get(char, 0)
                outputs[next_state].update(outputs[failures[next_state]])

        frozen_originals = {key: tuple(values) for key, values in originals.items()}
        return cls(
            originals_by_pattern=frozen_originals,
            transitions=tuple(dict(row) for row in transitions),
            failures=tuple(failures),
            outputs=tuple(tuple(sorted(row)) for row in outputs),
            empty_pattern_originals=frozen_originals.get("", ()),
        )

    def aggregate(self, values: Mapping[object, object]) -> dict[str, int]:
        """Aggregate values for all substring patterns in one automaton pass.

        Algorithm-Complexity: O(N)
        Algorithm-Rationale: N includes total normalized key characters and emitted matches; each inventory key is scanned once and each matched pattern is credited once per key.
        """
        totals = {
            original: 0
            for originals in self.originals_by_pattern.values()
            for original in originals
        }
        for raw_key, raw_value in values.items():
            state = 0
            matched: set[str] = set()
            for char in str(raw_key).lower():
                while state and char not in self.transitions[state]:
                    state = self.failures[state]
                state = self.transitions[state].get(char, 0)
                matched.update(self.outputs[state])
            if self.empty_pattern_originals:
                matched.add("")
            if not matched:
                continue
            value = int(raw_value)
            for pattern in matched:
                for original in self.originals_by_pattern[pattern]:
                    totals[original] += value
        return totals


__all__ = ["SubstringAggregatePlan"]

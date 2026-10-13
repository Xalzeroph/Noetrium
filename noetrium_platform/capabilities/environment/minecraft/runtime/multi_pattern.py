from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SubstringAggregatePlan:
    """Compiled case-insensitive multi-pattern matcher for inventory aggregation.

    The automaton is Aho-Corasick with shared failure/output links. A
    terminal pattern is stored exactly once rather than propagated into every
    suffix-dependent state. A value contributes at most once per requested
    pattern for each inventory key, including repeated occurrences.
    """

    originals_by_pattern: Mapping[str, tuple[str, ...]]
    transitions: tuple[Mapping[str, int], ...]
    failures: tuple[int, ...]
    outputs: tuple[tuple[str, ...], ...]
    output_links: tuple[int, ...]
    empty_pattern_originals: tuple[str, ...]

    @classmethod
    def compile(cls, patterns: Iterable[str]) -> "SubstringAggregatePlan":
        """Compile the requested patterns into a sparse failure automaton.

        Terminal storage is O(number of distinct non-empty patterns).
        The sparse automaton has at most one trie node per pattern character;
        failure-link searches are bounded by trie depth and do not duplicate
        inherited terminal payloads.
        """
        originals: dict[str, list[str]] = {}
        seen_originals: set[str] = set()
        for original in patterns:
            if original in seen_originals:
                continue
            seen_originals.add(original)
            normalized = original.lower()
            # A case-distinct query remains independently named, while an
            # identical repeated key is counted only once.
            originals.setdefault(normalized, []).append(original)

        transitions: list[dict[str, int]] = [{}]
        failures: list[int] = [0]
        outputs: list[set[str]] = [set()]
        output_links: list[int] = [0]
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
                    output_links.append(0)
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
                failure = failures[next_state]
                output_links[next_state] = (
                    failure if outputs[failure] else output_links[failure]
                )

        frozen_originals = {key: tuple(values) for key, values in originals.items()}
        return cls(
            originals_by_pattern=frozen_originals,
            transitions=tuple(dict(row) for row in transitions),
            failures=tuple(failures),
            outputs=tuple(tuple(sorted(row)) for row in outputs),
            output_links=tuple(output_links),
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
            visited_terminals: set[int] = set()
            for char in str(raw_key).lower():
                while state and char not in self.transitions[state]:
                    state = self.failures[state]
                state = self.transitions[state].get(char, 0)
                terminal = state if self.outputs[state] else self.output_links[state]
                while terminal and terminal not in visited_terminals:
                    visited_terminals.add(terminal)
                    matched.update(self.outputs[terminal])
                    terminal = self.output_links[terminal]
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

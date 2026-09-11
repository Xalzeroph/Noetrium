"""Immutable research-record contracts for cross-run comparison and exchange.

Records reference authoritative Run commits and evaluation outputs.  They do
not copy or mutate the Run journal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from noetrium_platform.foundation.kernel.kernel import (
    canonical_bytes,
    canonical_digest,
    require_sha256,
    strict_json_loads,
)


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value


def _digest(value: object, label: str) -> str:
    return require_sha256(_text(value, label), label)


def _texts(values: tuple[str, ...], label: str) -> None:
    if type(values) is not tuple or any(type(value) is not str or not value.strip() for value in values):
        raise TypeError(f"{label} must be a tuple of non-empty text")
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique")


@dataclass(frozen=True, slots=True)
class ResearchRunRecord:
    run_id: str
    head_commit_id: str
    program_digest: str
    binding_digest: str
    result_digest: str
    status: str

    def __post_init__(self) -> None:
        _text(self.run_id, "research run_id")
        _digest(self.head_commit_id, "research head_commit_id")
        _digest(self.program_digest, "research program_digest")
        _digest(self.binding_digest, "research binding_digest")
        _digest(self.result_digest, "research result_digest")
        _text(self.status, "research run status")

    def document(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "head_commit_id": self.head_commit_id,
            "program_digest": self.program_digest,
            "binding_digest": self.binding_digest,
            "result_digest": self.result_digest,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class ComparisonRecord:
    comparison_id: str
    run_ids: tuple[str, ...]
    evaluator_digest: str
    result_digest: str
    status: str

    def __post_init__(self) -> None:
        _text(self.comparison_id, "comparison_id")
        _texts(self.run_ids, "comparison run_ids")
        if len(self.run_ids) < 2:
            raise ValueError("comparison requires at least two runs")
        _digest(self.evaluator_digest, "comparison evaluator_digest")
        _digest(self.result_digest, "comparison result_digest")
        _text(self.status, "comparison status")

    def document(self) -> dict[str, object]:
        return {
            "comparison_id": self.comparison_id,
            "run_ids": list(self.run_ids),
            "evaluator_digest": self.evaluator_digest,
            "result_digest": self.result_digest,
            "status": self.status,
        }
@dataclass(frozen=True, slots=True)
class ForkRecord:
    fork_id: str
    source_run_id: str
    source_commit_id: str
    new_run_id: str
    change_digest: str
    isolation_policy: str

    def __post_init__(self) -> None:
        _digest(self.fork_id, "fork_id")
        _text(self.source_run_id, "fork source_run_id")
        _digest(self.source_commit_id, "fork source_commit_id")
        _text(self.new_run_id, "fork new_run_id")
        if self.source_run_id == self.new_run_id:
            raise ValueError("fork must create a new run identity")
        _digest(self.change_digest, "fork change_digest")
        _text(self.isolation_policy, "fork isolation_policy")
        expected = canonical_digest({
            "source_run_id": self.source_run_id,
            "source_commit_id": self.source_commit_id,
            "new_run_id": self.new_run_id,
            "change_digest": self.change_digest,
            "isolation_policy": self.isolation_policy,
        })
        if self.fork_id != expected:
            raise ValueError("fork_id does not match fork definition")

    def document(self) -> dict[str, object]:
        return {
            "fork_id": self.fork_id,
            "source_run_id": self.source_run_id,
            "source_commit_id": self.source_commit_id,
            "new_run_id": self.new_run_id,
            "change_digest": self.change_digest,
            "isolation_policy": self.isolation_policy,
        }


def fork_run(
    *,
    source_run_id: str,
    source_commit_id: str,
    new_run_id: str,
    change_digest: str,
    isolation_policy: str = "copy_on_write",
) -> ForkRecord:
    identity = canonical_digest({
        "source_run_id": source_run_id,
        "source_commit_id": source_commit_id,
        "new_run_id": new_run_id,
        "change_digest": change_digest,
        "isolation_policy": isolation_policy,
    })
    return ForkRecord(
        fork_id=identity,
        source_run_id=source_run_id,
        source_commit_id=source_commit_id,
        new_run_id=new_run_id,
        change_digest=change_digest,
        isolation_policy=isolation_policy,
    )


@dataclass(frozen=True, slots=True)
class ResearchPackage:
    package_id: str
    definition_digest: str
    runs: tuple[ResearchRunRecord, ...] = ()
    comparisons: tuple[ComparisonRecord, ...] = ()
    forks: tuple[ForkRecord, ...] = ()
    dependency_digests: tuple[str, ...] = ()
    package_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.package_id, "research package_id")
        _digest(self.definition_digest, "research definition_digest")
        if type(self.runs) is not tuple or any(not isinstance(item, ResearchRunRecord) for item in self.runs):
            raise TypeError("research package runs must be typed tuple")
        if type(self.comparisons) is not tuple or any(not isinstance(item, ComparisonRecord) for item in self.comparisons):
            raise TypeError("research package comparisons must be typed tuple")
        if type(self.forks) is not tuple or any(not isinstance(item, ForkRecord) for item in self.forks):
            raise TypeError("research package forks must be typed tuple")
        _texts(self.dependency_digests, "research dependency_digests")
        if len({item.run_id for item in self.runs}) != len(self.runs):
            raise ValueError("research package run identities must be unique")
        if len({item.comparison_id for item in self.comparisons}) != len(self.comparisons):
            raise ValueError("research package comparison identities must be unique")
        if len({item.fork_id for item in self.forks}) != len(self.forks):
            raise ValueError("research package fork identities must be unique")
        object.__setattr__(self, "package_digest", canonical_digest(self.document()))

    def document(self) -> dict[str, object]:
        return {
            "package_id": self.package_id,
            "definition_digest": self.definition_digest,
            "runs": [item.document() for item in self.runs],
            "comparisons": [item.document() for item in self.comparisons],
            "forks": [item.document() for item in self.forks],
            "dependency_digests": list(self.dependency_digests),
        }

    def export_bytes(self) -> bytes:
        return canonical_bytes({
            **self.document(),
            "package_digest": self.package_digest,
        })

    @classmethod
    def import_bytes(cls, raw: bytes) -> "ResearchPackage":
        value = strict_json_loads(raw)
        if not isinstance(value, dict):
            raise ValueError("research package document must be an object")
        required = {"package_id", "definition_digest", "runs", "comparisons", "forks", "dependency_digests", "package_digest"}
        if set(value) != required:
            raise ValueError("research package fields are not exact")
        runs = value["runs"]
        comparisons = value["comparisons"]
        forks = value["forks"]
        dependencies = value["dependency_digests"]
        if not all(isinstance(items, list) for items in (runs, comparisons, forks, dependencies)):
            raise TypeError("research package collections must be lists")
        package = cls(
            package_id=_text(value["package_id"], "package_id"),
            definition_digest=_digest(value["definition_digest"], "definition_digest"),
            runs=tuple(_decode_run(item) for item in runs),
            comparisons=tuple(_decode_comparison(item) for item in comparisons),
            forks=tuple(_decode_fork(item) for item in forks),
            dependency_digests=tuple(_digest(item, "dependency digest") for item in dependencies),
        )
        if canonical_bytes(value) != raw or package.package_digest != _digest(value["package_digest"], "package_digest"):
            raise ValueError("research package integrity mismatch")
        return package


def _row(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _decode_run(value: object) -> ResearchRunRecord:
    row = _row(value, "research run")
    if set(row) != {"run_id", "head_commit_id", "program_digest", "binding_digest", "result_digest", "status"}:
        raise ValueError("research run fields are not exact")
    return ResearchRunRecord(
        run_id=_text(row["run_id"], "run_id"),
        head_commit_id=_digest(row["head_commit_id"], "head_commit_id"),
        program_digest=_digest(row["program_digest"], "program_digest"),
        binding_digest=_digest(row["binding_digest"], "binding_digest"),
        result_digest=_digest(row["result_digest"], "result_digest"),
        status=_text(row["status"], "status"),
    )
def _decode_comparison(value: object) -> ComparisonRecord:
    row = _row(value, "comparison")
    if set(row) != {"comparison_id", "run_ids", "evaluator_digest", "result_digest", "status"}:
        raise ValueError("comparison fields are not exact")
    run_ids = row["run_ids"]
    if not isinstance(run_ids, list):
        raise TypeError("comparison run_ids must be a list")
    return ComparisonRecord(
        comparison_id=_text(row["comparison_id"], "comparison_id"),
        run_ids=tuple(_text(item, "comparison run_id") for item in run_ids),
        evaluator_digest=_digest(row["evaluator_digest"], "evaluator_digest"),
        result_digest=_digest(row["result_digest"], "result_digest"),
        status=_text(row["status"], "status"),
    )


def _decode_fork(value: object) -> ForkRecord:
    row = _row(value, "fork")
    if set(row) != {"fork_id", "source_run_id", "source_commit_id", "new_run_id", "change_digest", "isolation_policy"}:
        raise ValueError("fork fields are not exact")
    return ForkRecord(
        fork_id=_digest(row["fork_id"], "fork_id"),
        source_run_id=_text(row["source_run_id"], "source_run_id"),
        source_commit_id=_digest(row["source_commit_id"], "source_commit_id"),
        new_run_id=_text(row["new_run_id"], "new_run_id"),
        change_digest=_digest(row["change_digest"], "change_digest"),
        isolation_policy=_text(row["isolation_policy"], "isolation_policy"),
    )


__all__ = [
    "ComparisonRecord",
    "ForkRecord",
    "ResearchPackage",
    "ResearchRunRecord",
    "fork_run",
]

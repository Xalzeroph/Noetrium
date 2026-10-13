"""Unit-native immutable research records for comparison, forks, and exchange.

Static research record truth has exactly one carrier: :class:`NoetriumUnit`.
Durable stores may persist these Units, but they do not own a parallel record
model or a second content digest.
"""
from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    MachineCut,
    canonical_digest,
    require_sha256,
)
from noetrium_platform.foundation.kernel.structure import NoetriumUnit, structure_unit

RUN_RECORD_TRAIT = "research.run-record"
COMPARISON_RECORD_TRAIT = "research.comparison-record"
FORK_RECORD_TRAIT = "research.fork-record"
RESEARCH_PACKAGE_TRAIT = "research.package"


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value.strip()


def _digest(value: object, label: str) -> str:
    return require_sha256(_text(value, label), label)


def _texts(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if type(values) is not tuple or any(type(value) is not str or not value.strip() for value in values):
        raise TypeError(f"{label} must be a tuple of non-empty text")
    canonical = tuple(value.strip() for value in values)
    if len(set(canonical)) != len(canonical):
        raise ValueError(f"{label} must be unique")
    return canonical


def research_run_record(
    *,
    run_id: str,
    head_commit_id: str,
    program_digest: str,
    program_lock_digest: str,
    binding_digest: str,
    result_digest: str,
    status: str,
) -> NoetriumUnit:
    run_id = _text(run_id, "research run_id")
    return structure_unit(
        f"run-record:{run_id}",
        traits=(RUN_RECORD_TRAIT,),
        parameters={
            "run_id": run_id,
            "head_commit_id": _digest(head_commit_id, "research head_commit_id"),
            "program_digest": _digest(program_digest, "research program_digest"),
            "program_lock_digest": _digest(program_lock_digest, "research program_lock_digest"),
            "binding_digest": _digest(binding_digest, "research binding_digest"),
            "result_digest": _digest(result_digest, "research result_digest"),
            "status": _text(status, "research run status"),
        },
    )


def require_research_run_record(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(RUN_RECORD_TRAIT):
        raise TypeError("research run record must be research.run-record NoetriumUnit")
    return value


def run_record_value(value: NoetriumUnit, name: str):
    return require_research_run_record(value).parameters[name]


def comparison_record(
    *,
    comparison_id: str,
    run_ids: tuple[str, ...],
    evaluator_digest: str,
    result_digest: str,
    status: str,
) -> NoetriumUnit:
    comparison_id = _text(comparison_id, "comparison_id")
    run_ids = _texts(run_ids, "comparison run_ids")
    if len(run_ids) < 2:
        raise ValueError("comparison requires at least two runs")
    return structure_unit(
        f"comparison-record:{comparison_id}",
        traits=(COMPARISON_RECORD_TRAIT,),
        parameters={
            "comparison_id": comparison_id,
            "run_ids": run_ids,
            "evaluator_digest": _digest(evaluator_digest, "comparison evaluator_digest"),
            "result_digest": _digest(result_digest, "comparison result_digest"),
            "status": _text(status, "comparison status"),
        },
    )


def require_comparison_record(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(COMPARISON_RECORD_TRAIT):
        raise TypeError("comparison record must be research.comparison-record NoetriumUnit")
    return value


def comparison_record_value(value: NoetriumUnit, name: str):
    return require_comparison_record(value).parameters[name]


def fork_record(
    *,
    source_run_id: str,
    source_commit_id: str,
    new_run_id: str,
    change_digest: str,
    isolation_policy: str = "copy_on_write",
) -> NoetriumUnit:
    source_run_id = _text(source_run_id, "fork source_run_id")
    new_run_id = _text(new_run_id, "fork new_run_id")
    if source_run_id == new_run_id:
        raise ValueError("fork must create a new run identity")
    source_commit_id = _digest(source_commit_id, "fork source_commit_id")
    change_digest = _digest(change_digest, "fork change_digest")
    isolation_policy = _text(isolation_policy, "fork isolation_policy")
    fork_id = canonical_digest({
        "source_run_id": source_run_id,
        "source_commit_id": source_commit_id,
        "new_run_id": new_run_id,
        "change_digest": change_digest,
        "isolation_policy": isolation_policy,
    })
    return structure_unit(
        f"fork-record:{fork_id}",
        traits=(FORK_RECORD_TRAIT,),
        parameters={
            "fork_id": fork_id,
            "source_run_id": source_run_id,
            "source_commit_id": source_commit_id,
            "new_run_id": new_run_id,
            "change_digest": change_digest,
            "isolation_policy": isolation_policy,
        },
    )


def require_fork_record(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(FORK_RECORD_TRAIT):
        raise TypeError("fork record must be research.fork-record NoetriumUnit")
    expected = canonical_digest({
        "source_run_id": value.parameters["source_run_id"],
        "source_commit_id": value.parameters["source_commit_id"],
        "new_run_id": value.parameters["new_run_id"],
        "change_digest": value.parameters["change_digest"],
        "isolation_policy": value.parameters["isolation_policy"],
    })
    if value.parameters["fork_id"] != expected or value.unit_id != f"fork-record:{expected}":
        raise ValueError("fork record identity does not match fork semantics")
    return value


def fork_record_value(value: NoetriumUnit, name: str):
    return require_fork_record(value).parameters[name]


def research_package(
    *,
    package_id: str,
    definition_digest: str,
    runs: tuple[NoetriumUnit, ...] = (),
    comparisons: tuple[NoetriumUnit, ...] = (),
    forks: tuple[NoetriumUnit, ...] = (),
    dependency_digests: tuple[str, ...] = (),
) -> NoetriumUnit:
    package_id = _text(package_id, "research package_id")
    definition_digest = _digest(definition_digest, "research definition_digest")
    if type(runs) is not tuple:
        raise TypeError("research package runs must be tuple")
    if type(comparisons) is not tuple:
        raise TypeError("research package comparisons must be tuple")
    if type(forks) is not tuple:
        raise TypeError("research package forks must be tuple")
    for row in runs:
        require_research_run_record(row)
    for row in comparisons:
        require_comparison_record(row)
    for row in forks:
        require_fork_record(row)
    dependency_digests = tuple(
        _digest(row, "research dependency digest")
        for row in _texts(dependency_digests, "research dependency_digests")
    )
    run_ids = tuple(str(run_record_value(row, "run_id")) for row in runs)
    comparison_ids = tuple(str(comparison_record_value(row, "comparison_id")) for row in comparisons)
    fork_ids = tuple(str(fork_record_value(row, "fork_id")) for row in forks)
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("research package run identities must be unique")
    if len(set(comparison_ids)) != len(comparison_ids):
        raise ValueError("research package comparison identities must be unique")
    if len(set(fork_ids)) != len(fork_ids):
        raise ValueError("research package fork identities must be unique")
    members = tuple(
        sorted(
            runs + comparisons + forks,
            key=lambda row: (row.traits, row.unit_id, row.unit_digest),
        )
    )
    return structure_unit(
        package_id,
        traits=(RESEARCH_PACKAGE_TRAIT,),
        parameters={
            "package_id": package_id,
            "definition_digest": definition_digest,
            "dependency_digests": dependency_digests,
        },
        members=members,
    )


def require_research_package(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(RESEARCH_PACKAGE_TRAIT):
        raise TypeError("research package must be research.package NoetriumUnit")
    if value.parameters["package_id"] != value.unit_id:
        raise ValueError("research package Unit identity drifted")
    for member in value.members:
        if not (
            member.has_trait(RUN_RECORD_TRAIT)
            or member.has_trait(COMPARISON_RECORD_TRAIT)
            or member.has_trait(FORK_RECORD_TRAIT)
        ):
            raise ValueError("research package contains unsupported member")
    return value


def research_package_id(value: NoetriumUnit) -> str:
    return str(require_research_package(value).parameters["package_id"])


def research_package_digest(value: NoetriumUnit) -> str:
    return require_research_package(value).unit_digest


def research_package_runs(value: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    return tuple(row for row in require_research_package(value).members if row.has_trait(RUN_RECORD_TRAIT))


def research_package_comparisons(value: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    return tuple(row for row in require_research_package(value).members if row.has_trait(COMPARISON_RECORD_TRAIT))


def research_package_forks(value: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    return tuple(row for row in require_research_package(value).members if row.has_trait(FORK_RECORD_TRAIT))


def record_run_cut(
    cut: MachineCut,
    *,
    binding_digest: str,
    status: str,
    result: object | None = None,
) -> NoetriumUnit:
    """Project one authoritative Run Machine cut into an immutable Unit record."""
    if not isinstance(cut, MachineCut):
        raise TypeError("record_run_cut requires MachineCut")
    binding_digest = _digest(binding_digest, "research binding_digest")
    status = _text(status, "research run status")
    result_digest = (
        result
        if type(result) is str and len(result) == 64
        else canonical_digest({
            "machine_cut": cut.cut_digest,
            "result": result,
            "status": status,
        })
    )
    return research_run_record(
        run_id=cut.machine_id,
        head_commit_id=cut.commit_id,
        program_digest=cut.program_digest,
        program_lock_digest=cut.program_lock_digest,
        binding_digest=binding_digest,
        result_digest=_digest(result_digest, "research result_digest"),
        status=status,
    )


def compare_run_records(
    *,
    comparison_id: str,
    runs: tuple[NoetriumUnit, ...],
    evaluator: object,
    result: object,
    status: str,
) -> NoetriumUnit:
    if type(runs) is not tuple or len(runs) < 2:
        raise ValueError("comparison requires at least two run records")
    for row in runs:
        require_research_run_record(row)
    return comparison_record(
        comparison_id=comparison_id,
        run_ids=tuple(str(run_record_value(row, "run_id")) for row in runs),
        evaluator_digest=(
            evaluator if type(evaluator) is str and len(evaluator) == 64
            else canonical_digest(evaluator)
        ),
        result_digest=(
            result if type(result) is str and len(result) == 64
            else canonical_digest(result)
        ),
        status=_text(status, "comparison status"),
    )


def fork_run(
    *,
    source_run_id: str,
    source_commit_id: str,
    new_run_id: str,
    change_digest: str,
    isolation_policy: str = "copy_on_write",
) -> NoetriumUnit:
    return fork_record(
        source_run_id=source_run_id,
        source_commit_id=source_commit_id,
        new_run_id=new_run_id,
        change_digest=change_digest,
        isolation_policy=isolation_policy,
    )


def build_research_package(
    *,
    package_id: str,
    definition: object,
    runs: tuple[NoetriumUnit, ...],
    comparisons: tuple[NoetriumUnit, ...] = (),
    forks: tuple[NoetriumUnit, ...] = (),
    dependencies: tuple[str, ...] = (),
) -> NoetriumUnit:
    definition_digest = (
        definition if type(definition) is str and len(definition) == 64
        else canonical_digest(definition)
    )
    return research_package(
        package_id=package_id,
        definition_digest=definition_digest,
        runs=runs,
        comparisons=comparisons,
        forks=forks,
        dependency_digests=dependencies,
    )


__all__ = [
    "COMPARISON_RECORD_TRAIT",
    "FORK_RECORD_TRAIT",
    "RESEARCH_PACKAGE_TRAIT",
    "RUN_RECORD_TRAIT",
    "build_research_package",
    "compare_run_records",
    "comparison_record",
    "comparison_record_value",
    "fork_record",
    "fork_record_value",
    "fork_run",
    "record_run_cut",
    "research_package",
    "research_package_comparisons",
    "research_package_digest",
    "research_package_forks",
    "research_package_id",
    "research_package_runs",
    "research_run_record",
    "require_comparison_record",
    "require_fork_record",
    "require_research_package",
    "require_research_run_record",
    "run_record_value",
]

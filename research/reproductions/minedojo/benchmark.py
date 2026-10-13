"""Reproduction-owned binding to the canonical MineDojo benchmark cut.

The benchmark authority lives under research/benchmarks/minedojo.  This module
exists so the reproduction package can declare a benchmark scientific asset
without duplicating task/cut semantics.
"""

from research.benchmarks.minedojo import (
    MINEDOJO_ALL_SPLIT,
    MINEDOJO_BENCHMARK_ID,
    MINEDOJO_REPOSITORY,
    MINEDOJO_REVISION_ID,
    MINEDOJO_TASK_SCHEMA_ID,
    MineDojoTaskRecord,
    bind_minedojo_cut,
    build_minedojo_source,
    build_minedojo_task_set,
    minedojo_selection_policy_digest,
)

__all__ = [
    "MINEDOJO_ALL_SPLIT",
    "MINEDOJO_BENCHMARK_ID",
    "MINEDOJO_REPOSITORY",
    "MINEDOJO_REVISION_ID",
    "MINEDOJO_TASK_SCHEMA_ID",
    "MineDojoTaskRecord",
    "bind_minedojo_cut",
    "build_minedojo_source",
    "build_minedojo_task_set",
    "minedojo_selection_policy_digest",
]

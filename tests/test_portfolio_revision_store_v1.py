from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.foundation.portfolio.api import (
    PortfolioRevision,
    PortfolioRevisionConflict,
    PortfolioRevisionNotFound,
)
from noetrium_platform.foundation.portfolio.runtime import (
    InMemoryPortfolioRevisionStore,
    SQLitePortfolioRevisionStore,
)


def _root(subject: str = "sem") -> PortfolioRevision:
    return PortfolioRevision(subject, "1" * 64, (), "root")


def _child(parent: PortfolioRevision, payload: str = "2" * 64) -> PortfolioRevision:
    return PortfolioRevision(
        parent.subject_id,
        payload,
        (parent.revision_digest,),
        "child",
    )


def _exercise(store) -> None:
    root = store.commit(_root())
    assert store.commit(root) == root

    child = store.commit(_child(root))
    assert store.revision("sem", child.revision_digest) == child

    branch = store.move_branch(
        "sem",
        "main",
        root.revision_digest,
        expected_revision_digest=None,
    )
    assert branch.generation == 1
    advanced = store.move_branch(
        "sem",
        "main",
        child.revision_digest,
        expected_revision_digest=root.revision_digest,
    )
    assert advanced.generation == 2
    assert store.branch("sem", "main") == advanced

    with pytest.raises(PortfolioRevisionConflict, match="compare-and-swap"):
        store.move_branch(
            "sem",
            "main",
            root.revision_digest,
            expected_revision_digest=root.revision_digest,
        )

    tag = store.tag("sem", "confirmatory-v1", child.revision_digest)
    assert store.tag("sem", "confirmatory-v1", child.revision_digest) == tag
    assert store.resolve_tag("sem", "confirmatory-v1") == tag
    with pytest.raises(PortfolioRevisionConflict, match="immutable"):
        store.tag("sem", "confirmatory-v1", root.revision_digest)

    missing_parent = PortfolioRevision(
        "sem",
        "3" * 64,
        ("f" * 64,),
        "orphan",
    )
    with pytest.raises(PortfolioRevisionNotFound):
        store.commit(missing_parent)


def test_in_memory_portfolio_revision_graph_is_git_like_and_fail_closed() -> None:
    _exercise(InMemoryPortfolioRevisionStore())


def test_sqlite_portfolio_revision_graph_reopens_exactly(tmp_path: Path) -> None:
    path = tmp_path / "portfolio-revisions.sqlite3"
    store = SQLitePortfolioRevisionStore(path)
    _exercise(store)

    reopened = SQLitePortfolioRevisionStore(path)
    root = _root()
    child = _child(root)
    assert reopened.revision("sem", root.revision_digest) == root
    assert reopened.revision("sem", child.revision_digest) == child
    assert reopened.branch("sem", "main").revision_digest == child.revision_digest
    assert reopened.branch("sem", "main").generation == 2
    assert (
        reopened.resolve_tag("sem", "confirmatory-v1").revision_digest
        == child.revision_digest
    )


def test_merge_parent_order_is_part_of_revision_identity() -> None:
    left = _root("paper")
    right = PortfolioRevision("paper", "2" * 64, (), "right")
    forward = PortfolioRevision(
        "paper",
        "3" * 64,
        (left.revision_digest, right.revision_digest),
        "merge",
    )
    reverse = PortfolioRevision(
        "paper",
        "3" * 64,
        (right.revision_digest, left.revision_digest),
        "merge",
    )
    assert forward.revision_digest != reverse.revision_digest

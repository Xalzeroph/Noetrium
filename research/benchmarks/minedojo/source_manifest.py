from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest

from .authority import MINEDOJO_AUDITED_COMMIT


MINEDOJO_TASK_DESCRIPTION_TREE_GIT_SHA = (
    "03b41574f3f7ca6129b260d250ee83f7f4bf54b8"
)


@dataclass(frozen=True, slots=True, order=True)
class MineDojoSourceBlob:
    path: str
    git_blob_sha: str
    size_bytes: int

    def __post_init__(self) -> None:
        if type(self.path) is not str or not self.path.strip():
            raise ValueError("MineDojo source blob path is required")
        if (
            type(self.git_blob_sha) is not str
            or len(self.git_blob_sha) != 40
            or any(
                ch not in "0123456789abcdef"
                for ch in self.git_blob_sha
            )
        ):
            raise ValueError("MineDojo source blob requires git SHA-1")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise ValueError(
                "MineDojo source blob size must be non-negative"
            )


MINEDOJO_TASK_SOURCE_BLOBS = (
    MineDojoSourceBlob(
        "minedojo/tasks/__init__.py",
        "f9bad606f2066f17b548a269efd029e90980da89",
        15150,
    ),
    MineDojoSourceBlob(
        "minedojo/tasks/description_files/creative_tasks.yaml",
        "e298c30556e6f600f719690fddc24e7ca15d42a0",
        521736,
    ),
    MineDojoSourceBlob(
        "minedojo/tasks/description_files/playthrough_task.yaml",
        "f7a06f080b53ac499f280d9b2bccf5b1f3f96d91",
        761,
    ),
    MineDojoSourceBlob(
        "minedojo/tasks/description_files/programmatic_tasks.yaml",
        "a051d5f0e8a47696aa153501bf27fcdc74db94d6",
        710666,
    ),
    MineDojoSourceBlob(
        "minedojo/tasks/description_files/tasks_specs.yaml",
        "d218e3fe039cf3e2627a4c70c589c1d9679d3515",
        37430,
    ),
    MineDojoSourceBlob(
        "minedojo/tasks/description_files/tasks_suite.yaml",
        "a1f067ebd22510b1ddedba2ec9f4abb640829d37",
        4673,
    ),
)


def minedojo_task_source_manifest_digest() -> str:
    return canonical_digest({
        "repository": "https://github.com/MineDojo/MineDojo",
        "commit": MINEDOJO_AUDITED_COMMIT,
        "description_tree_git_sha": (
            MINEDOJO_TASK_DESCRIPTION_TREE_GIT_SHA
        ),
        "blobs": tuple(
            {
                "path": row.path,
                "git_blob_sha": row.git_blob_sha,
                "size_bytes": row.size_bytes,
            }
            for row in MINEDOJO_TASK_SOURCE_BLOBS
        ),
    })


__all__ = [
    "MINEDOJO_TASK_DESCRIPTION_TREE_GIT_SHA",
    "MINEDOJO_TASK_SOURCE_BLOBS",
    "MineDojoSourceBlob",
    "minedojo_task_source_manifest_digest",
]

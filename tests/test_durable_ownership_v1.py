from __future__ import annotations

from noetrium_platform.evidence.artifact.content.providers._publication import (
    PublicationLock,
    PublicationLockBusy,
    PublicationLockUnavailable,
    fsync_directory,
)
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import (
    fsync_directory as kernel_fsync_directory,
)
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import (
    InterprocessFileLock,
    InterprocessLockBusy,
    InterprocessLockUnavailable,
)


def test_artifact_publication_uses_kernel_durability_authority() -> None:
    assert issubclass(PublicationLock, InterprocessFileLock)
    assert PublicationLock.__init__ is not InterprocessFileLock.__init__
    assert PublicationLockBusy is InterprocessLockBusy
    assert PublicationLockUnavailable is InterprocessLockUnavailable
    assert fsync_directory is kernel_fsync_directory

from __future__ import annotations

import pytest

from noetrium_platform.infrastructure.lifecycle.process.supervision.runtime import windows_job


class _RetryableKernel32:
    def __init__(self) -> None:
        self.close_calls = 0

    def CloseHandle(self, handle) -> bool:
        del handle
        self.close_calls += 1
        return self.close_calls >= 2


def test_windows_job_close_preserves_physical_handle_until_close_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = _RetryableKernel32()
    monkeypatch.setattr(
        windows_job.WindowsProcessJob,
        "_kernel32",
        staticmethod(lambda: kernel),
    )
    monkeypatch.setattr(windows_job.ctypes, "get_last_error", lambda: 5, raising=False)

    job = windows_job.WindowsProcessJob(123)

    with pytest.raises(
        windows_job.WindowsProcessJobError,
        match="CloseHandle\\(job\\) failed",
    ):
        job.close()

    assert job._job_handle == 123
    assert not job._closed
    assert kernel.close_calls == 1

    job.close()

    assert job._job_handle == 0
    assert job._closed
    assert kernel.close_calls == 2

    job.close()
    assert kernel.close_calls == 2

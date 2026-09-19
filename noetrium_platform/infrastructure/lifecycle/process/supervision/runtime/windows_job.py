from __future__ import annotations

"""Windows Job Object ownership for one subprocess tree.

The root process is created suspended, attached to a kill-on-close Job Object,
and only then resumed. This closes the spawn->assign race: every descendant is
born inside the owned job unless it uses a disallowed breakaway mode.
"""

import ctypes
from ctypes import wintypes


_CREATE_SUSPENDED = 0x00000004
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_SUSPEND_RESUME = 0x0800
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


class WindowsProcessJobError(RuntimeError):
    pass


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]

class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def suspended_creation_flag() -> int:
    return _CREATE_SUSPENDED


class WindowsProcessJob:
    """Own a suspended root process and all descendants through one Job Object."""

    def __init__(self, job_handle: int) -> None:
        self._job_handle = int(job_handle)
        self._closed = False

    @staticmethod
    def _kernel32():
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateJobObject.restype = wintypes.BOOL
        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        return kernel

    @classmethod
    def attach_suspended(cls, process_id: int) -> "WindowsProcessJob":
        kernel = cls._kernel32()
        job = kernel.CreateJobObjectW(None, None)
        if not job:
            raise WindowsProcessJobError(
                f"CreateJobObjectW failed: winerror={ctypes.get_last_error()}"
            )
        info = _ExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            error = ctypes.get_last_error()
            kernel.CloseHandle(job)
            raise WindowsProcessJobError(f"SetInformationJobObject failed: winerror={error}")

        access = (
            _PROCESS_TERMINATE
            | _PROCESS_SET_QUOTA
            | _PROCESS_SUSPEND_RESUME
            | _PROCESS_QUERY_LIMITED_INFORMATION
        )
        process = kernel.OpenProcess(access, False, int(process_id))
        if not process:
            error = ctypes.get_last_error()
            kernel.CloseHandle(job)
            raise WindowsProcessJobError(f"OpenProcess failed: winerror={error}")
        try:
            if not kernel.AssignProcessToJobObject(job, process):
                error = ctypes.get_last_error()
                kernel.TerminateProcess(process, 127)
                raise WindowsProcessJobError(
                    f"AssignProcessToJobObject failed: winerror={error}"
                )
            ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
            ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
            ntdll.NtResumeProcess.restype = ctypes.c_long
            status = int(ntdll.NtResumeProcess(process))
            if status < 0:
                kernel.TerminateJobObject(job, 127)
                raise WindowsProcessJobError(
                    f"NtResumeProcess failed: ntstatus={status:#x}"
                )
            return cls(int(job))
        except BaseException:
            kernel.CloseHandle(job)
            raise
        finally:
            kernel.CloseHandle(process)

    def terminate(self, exit_code: int = 1) -> None:
        if self._closed:
            return
        kernel = self._kernel32()
        if not kernel.TerminateJobObject(wintypes.HANDLE(self._job_handle), int(exit_code)):
            error = ctypes.get_last_error()
            if error not in {0, 6}:
                raise WindowsProcessJobError(
                    f"TerminateJobObject failed: winerror={error}"
                )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        handle = self._job_handle
        self._job_handle = 0
        if handle:
            kernel = self._kernel32()
            if not kernel.CloseHandle(wintypes.HANDLE(handle)):
                error = ctypes.get_last_error()
                if error not in {0, 6}:
                    raise WindowsProcessJobError(
                        f"CloseHandle(job) failed: winerror={error}"
                    )

    def __enter__(self) -> "WindowsProcessJob":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


__all__ = [
    "WindowsProcessJob",
    "WindowsProcessJobError",
    "suspended_creation_flag",
]

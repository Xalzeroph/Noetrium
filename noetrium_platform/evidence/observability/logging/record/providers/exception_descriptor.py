from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.errors import SafeExceptionDescriptor, describe_exception


class KernelExceptionDescriptor:
    """Platform adapter that exposes safe kernel exception semantics."""

    def describe(self, exc: BaseException) -> SafeExceptionDescriptor:
        return describe_exception(exc)


__all__ = ["KernelExceptionDescriptor"]

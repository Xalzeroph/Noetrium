from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.errors import (
    describe_exception,
    exception_leaves,
)


def test_exception_group_descriptor_preserves_deduplicated_leaf_causes() -> None:
    error = ExceptionGroup(
        "batch failed",
        [
            ValueError("same"),
            ExceptionGroup(
                "nested",
                [
                    RuntimeError("other"),
                    ValueError("same"),
                ],
            ),
        ],
    )

    leaves = exception_leaves(error)
    assert tuple(type(row) for row in leaves) == (
        ValueError,
        RuntimeError,
        ValueError,
    )

    descriptor = describe_exception(error)
    assert descriptor.qualified_type == "builtins.ExceptionGroup"
    assert "exception_group_leaves=3" in descriptor.safe_message
    assert "exception_group_leaf_kinds=2" in descriptor.safe_message
    assert "x2 builtins.ValueError: same" in descriptor.safe_message
    assert "x1 builtins.RuntimeError: other" in descriptor.safe_message
    assert descriptor == describe_exception(error)


def test_exception_group_descriptor_redacts_leaf_secrets() -> None:
    descriptor = describe_exception(
        ExceptionGroup(
            "unsafe",
            [RuntimeError("token=supersecretvalue")],
        )
    )
    assert "supersecretvalue" not in descriptor.safe_message
    assert "<REDACTED>" in descriptor.safe_message



def test_exception_group_descriptor_preserves_leaf_location_and_cause() -> None:
    try:
        try:
            raise OSError("socket refused")
        except OSError as cause:
            raise RuntimeError("branch start failed") from cause
    except RuntimeError as wrapped:
        descriptor = describe_exception(ExceptionGroup("batch", [wrapped]))

    assert "RuntimeError: branch start failed" in descriptor.safe_message
    assert "caused by builtins.OSError: socket refused" in descriptor.safe_message
    assert "at test_exception_group_descriptor_v1.py:" in descriptor.safe_message

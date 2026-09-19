from __future__ import annotations

import pytest

from noetrium_platform.research.experimentation.checkpoint.api import (
    CheckpointCapturePolicy,
    CheckpointTrigger,
)


def test_capture_policy_requests_without_claiming_checkpoint_authority() -> None:
    policy = CheckpointCapturePolicy(
        (
            CheckpointTrigger.every_turns(8),
            CheckpointTrigger.every_tokens(1000),
            CheckpointTrigger.every_seconds(120.0),
            CheckpointTrigger.manual(),
        )
    )
    assert policy.should_request(turns_since_checkpoint=7) is False
    assert policy.should_request(turns_since_checkpoint=8) is True
    assert policy.should_request(tokens_since_checkpoint=1000) is True
    assert policy.should_request(elapsed_seconds=120.0) is True
    assert policy.should_request(manual=True) is True


def test_capture_policy_identity_is_order_independent_but_threshold_sensitive() -> None:
    left = CheckpointCapturePolicy(
        (CheckpointTrigger.every_tokens(100), CheckpointTrigger.every_turns(4))
    )
    right = CheckpointCapturePolicy(
        (CheckpointTrigger.every_turns(4), CheckpointTrigger.every_tokens(100))
    )
    changed = CheckpointCapturePolicy(
        (CheckpointTrigger.every_turns(5), CheckpointTrigger.every_tokens(100))
    )
    assert left.policy_digest == right.policy_digest
    assert left.policy_digest != changed.policy_digest


def test_capture_policy_rejects_ambiguous_or_invalid_triggers() -> None:
    with pytest.raises(ValueError, match="unique"):
        CheckpointCapturePolicy(
            (CheckpointTrigger.every_turns(2), CheckpointTrigger.every_turns(3))
        )
    with pytest.raises(ValueError, match="positive"):
        CheckpointTrigger.every_tokens(0)

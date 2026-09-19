from __future__ import annotations

from noetrium_platform.capabilities.environment.minecraft.providers.readiness import probe_node


def test_readiness_runner_failure_keeps_bounded_redacted_fingerprint() -> None:
    def runner(command, **kwargs):
        del command, kwargs
        raise OSError("secret-token-must-not-leak")

    probe = probe_node(runner=runner)

    assert probe.ok is False
    assert probe.cause_code == "NODE_NOT_EXECUTABLE"
    assert "OSError[" in probe.detail
    assert "secret-token-must-not-leak" not in probe.detail

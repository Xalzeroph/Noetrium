from __future__ import annotations

from noetrium_platform.composition.model_stack_materialization import (
    DockerModelStackMaterializer,
)
from noetrium_platform.infrastructure.lifecycle.process.api import LocalCommandResult


class _Runner:
    def __init__(self, *, initially_present: bool) -> None:
        self.present = initially_present
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv, **_kwargs):
        args = tuple(argv)
        self.calls.append(args)
        if args[1:3] == ("image", "inspect"):
            if self.present:
                return LocalCommandResult(args, 0, "sha256:" + "a" * 64 + "\n", "")
            return LocalCommandResult(args, 1, "", "not found")
        if args[1] == "pull":
            self.present = True
            return LocalCommandResult(args, 0, "pulled", "")
        raise AssertionError(f"unexpected command: {args!r}")


def _materializer(runner: _Runner) -> DockerModelStackMaterializer:
    value = object.__new__(DockerModelStackMaterializer)
    value._runner = runner
    value._docker = "docker"
    value._vllm_default = "vllm/vllm-openai:v0.8.5"
    value._pull_timeout = 3600.0
    return value


def test_exact_platform_vllm_release_is_reused_without_inventory_scan() -> None:
    runner = _Runner(initially_present=True)
    source, digest = _materializer(runner)._resolve_vllm_image()
    assert source == "vllm/vllm-openai:v0.8.5"
    assert digest == "a" * 64
    assert runner.calls == [
        ("docker", "image", "inspect", "--format", "{{.Id}}", source),
    ]


def test_missing_platform_vllm_release_pulls_only_the_pinned_tag() -> None:
    runner = _Runner(initially_present=False)
    source, digest = _materializer(runner)._resolve_vllm_image()
    assert source == "vllm/vllm-openai:v0.8.5"
    assert digest == "a" * 64
    assert runner.calls == [
        ("docker", "image", "inspect", "--format", "{{.Id}}", source),
        ("docker", "pull", source),
        ("docker", "image", "inspect", "--format", "{{.Id}}", source),
    ]

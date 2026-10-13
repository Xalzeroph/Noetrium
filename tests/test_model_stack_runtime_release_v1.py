from __future__ import annotations

import json

from noetrium_platform.composition.model_stack_materialization import (
    DockerModelStackMaterializer,
    _VLLM_PATCHED_SOURCE,
    _VLLM_PATCH_REVISION,
)
from noetrium_platform.infrastructure.lifecycle.process.api import LocalCommandResult


_BASE_SOURCE = "vllm/vllm-openai:v0.8.5"
_BASE_DIGEST = "a" * 64
_PATCHED_DIGEST = "b" * 64


class _Runner:
    def __init__(self, *, base_present: bool, patched_present: bool) -> None:
        self.base_present = base_present
        self.patched_present = patched_present
        self.calls: list[tuple[str, ...]] = []

    @staticmethod
    def _result(args, returncode: int, stdout: str = "", stderr: str = ""):
        return LocalCommandResult(args, returncode, stdout, stderr)

    def run(self, argv, **_kwargs):
        args = tuple(argv)
        self.calls.append(args)

        if args[1:3] == ("image", "inspect"):
            source = args[-1]
            format_value = args[4]
            if source == _BASE_SOURCE:
                if not self.base_present:
                    return self._result(args, 1, stderr="not found")
                if format_value != "{{.Id}}":
                    raise AssertionError(f"unexpected base inspect format: {args!r}")
                return self._result(args, 0, "sha256:" + _BASE_DIGEST + "\n")

            if source == _VLLM_PATCHED_SOURCE:
                if not self.patched_present:
                    return self._result(args, 1, stderr="not found")
                if format_value == "{{.Id}}":
                    return self._result(args, 0, "sha256:" + _PATCHED_DIGEST + "\n")
                if format_value == "{{json .Config.Labels}}":
                    return self._result(
                        args,
                        0,
                        json.dumps(
                            {
                                "io.noetrium.vllm.base-image-id": "sha256:" + _BASE_DIGEST,
                                "io.noetrium.vllm.patch-revision": _VLLM_PATCH_REVISION,
                            },
                            sort_keys=True,
                        )
                        + "\n",
                    )
                raise AssertionError(f"unexpected patched inspect format: {args!r}")

            raise AssertionError(f"unexpected image inspect source: {args!r}")

        if args[1] == "pull":
            assert args == ("docker", "pull", _BASE_SOURCE)
            self.base_present = True
            return self._result(args, 0, "pulled")

        if args[1] == "build":
            assert "--pull=false" in args
            assert _VLLM_PATCHED_SOURCE in args
            self.patched_present = True
            return self._result(args, 0, "built")

        raise AssertionError(f"unexpected command: {args!r}")


def _materializer(runner: _Runner, root) -> DockerModelStackMaterializer:
    value = object.__new__(DockerModelStackMaterializer)
    value._runner = runner
    value._docker = "docker"
    value._vllm_default = _BASE_SOURCE
    value._pull_timeout = 3600.0
    value._root = root
    return value


def test_exact_noetrium_vllm_release_is_reused_without_rebuild(tmp_path) -> None:
    runner = _Runner(base_present=True, patched_present=True)

    source, digest = _materializer(runner, tmp_path)._resolve_vllm_image()

    assert source == _VLLM_PATCHED_SOURCE
    assert digest == _PATCHED_DIGEST
    assert not any(call[1] in {"pull", "build"} for call in runner.calls)
    assert runner.calls[0] == (
        "docker",
        "image",
        "inspect",
        "--format",
        "{{.Id}}",
        _BASE_SOURCE,
    )
    assert any(
        call[1:3] == ("image", "inspect")
        and call[4] == "{{json .Config.Labels}}"
        and call[-1] == _VLLM_PATCHED_SOURCE
        for call in runner.calls
    )


def test_missing_noetrium_vllm_release_pulls_base_then_builds_patch_once(tmp_path) -> None:
    runner = _Runner(base_present=False, patched_present=False)

    source, digest = _materializer(runner, tmp_path)._resolve_vllm_image()

    assert source == _VLLM_PATCHED_SOURCE
    assert digest == _PATCHED_DIGEST
    pulls = [call for call in runner.calls if call[1] == "pull"]
    builds = [call for call in runner.calls if call[1] == "build"]
    assert pulls == [("docker", "pull", _BASE_SOURCE)]
    assert len(builds) == 1
    assert "--pull=false" in builds[0]
    assert _VLLM_PATCHED_SOURCE in builds[0]

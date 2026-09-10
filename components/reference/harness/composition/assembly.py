"""Composition helpers for assembling a deterministic Harness profile."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from ..api import HarnessNodePort, HarnessNodeSpec, HarnessPluginSpec, HarnessProfile, HarnessProfileMode
from ..runtime import HarnessContext, HarnessRuntime


@dataclass(frozen=True, slots=True)
class HarnessAssembly:
    runtime: HarnessRuntime
    profile: HarnessProfile

    def start(self) -> HarnessProfile:
        return self.runtime.start(self.profile)


def compose_harness(
    profile_id: str,
    *,
    plugins: Iterable[
        tuple[HarnessPluginSpec, Callable[[HarnessContext], object | None]]
    ] = (),
    nodes: Iterable[tuple[HarnessNodeSpec, Callable[[HarnessContext], HarnessNodePort]]] = (),
    mode: HarnessProfileMode = HarnessProfileMode.STUDY,
) -> HarnessAssembly:
    """Build and compile a profile in one explicit composition call."""

    runtime = HarnessRuntime(mode=mode)
    for spec, factory in plugins:
        runtime.register_plugin(spec, factory)
    for spec, factory in nodes:
        runtime.register_node(spec, factory)
    return HarnessAssembly(runtime, runtime.compile(profile_id, mode=mode))


__all__ = ["HarnessAssembly", "compose_harness"]

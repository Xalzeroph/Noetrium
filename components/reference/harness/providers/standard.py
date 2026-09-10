"""Small standard providers that make downstream Harness authoring terse."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from noetrium.contracts.json import JsonValue

from ..runtime import HarnessContext


@dataclass(frozen=True, slots=True)
class ServiceBundlePlugin:
    """Install a fixed service bundle and optionally dispose it."""

    services: Mapping[str, object]
    on_dispose: Callable[[], object] | None = None

    def install(self, context: HarnessContext) -> Callable[[], object]:
        for key, service in self.services.items():
            context.provide(key, service)

        def dispose() -> object:
            if self.on_dispose is None:
                return None
            return self.on_dispose()

        return dispose


@dataclass(frozen=True, slots=True)
class CallbackHarnessNode:
    """Adapt a plain function into a typed Harness node."""

    callback: Callable[[HarnessContext, Mapping[str, JsonValue]], Mapping[str, JsonValue]]

    def run(
        self,
        context: HarnessContext,
        state: Mapping[str, JsonValue],
    ) -> Mapping[str, JsonValue]:
        outputs = self.callback(context, state)
        if not isinstance(outputs, Mapping):
            raise TypeError("harness node callback must return a mapping")
        return outputs


def service_plugin(
    services: Mapping[str, object],
    *,
    on_dispose: Callable[[], object] | None = None,
) -> Callable[[HarnessContext], Callable[[], object]]:
    """Return a plugin factory suitable for HarnessRuntime.register_plugin."""

    bundle = ServiceBundlePlugin(services, on_dispose)

    def install(context: HarnessContext) -> Callable[[], object]:
        return bundle.install(context)

    return install


def callback_node(
    callback: Callable[[HarnessContext, Mapping[str, JsonValue]], Mapping[str, JsonValue]],
) -> Callable[[HarnessContext], CallbackHarnessNode]:
    """Return a node factory suitable for HarnessRuntime.register_node."""

    def bind(_context: HarnessContext) -> CallbackHarnessNode:
        return CallbackHarnessNode(callback)

    return bind


__all__ = [
    "CallbackHarnessNode",
    "ServiceBundlePlugin",
    "callback_node",
    "service_plugin",
]

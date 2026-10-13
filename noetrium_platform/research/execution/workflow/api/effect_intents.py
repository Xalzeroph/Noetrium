from __future__ import annotations

from typing import Protocol

from noetrium_platform.capabilities.api import EffectIntentPrepareResult
from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, EffectReceipt
from noetrium_platform.foundation.kernel.unit import NoetriumUnit


class EffectIntentOperationPort(Protocol):
    """Workflow-facing access to the Unit-native Effect Journal Authority."""

    @property
    def durability(self) -> str: ...

    @property
    def component_identity(self) -> ComponentIdentity: ...

    def close(self) -> None: ...

    def inspect(self, intent: NoetriumUnit) -> NoetriumUnit | None: ...

    def require_scope_clear(self, intent: NoetriumUnit) -> None: ...

    def prepare(self, intent: NoetriumUnit) -> EffectIntentPrepareResult: ...

    def record_result(
        self,
        intent: NoetriumUnit,
        effect: EffectReceipt | None,
        *,
        result_snapshot: NoetriumUnit | None = None,
    ) -> NoetriumUnit: ...

    def record_terminal_result(
        self,
        intent: NoetriumUnit,
        effect: EffectReceipt,
        *,
        result_snapshot: NoetriumUnit | None = None,
        consumption: NoetriumUnit | None = None,
    ) -> NoetriumUnit: ...

    def record_reconciled(
        self,
        intent: NoetriumUnit,
        effect: EffectReceipt,
        *,
        result_snapshot: NoetriumUnit | None = None,
    ) -> NoetriumUnit: ...

    def record_consumed(
        self,
        intent: NoetriumUnit,
        consumption: NoetriumUnit,
    ) -> NoetriumUnit: ...

    def record_not_applied(
        self,
        intent: NoetriumUnit,
        effect: EffectReceipt,
    ) -> NoetriumUnit: ...

    def record_indeterminate(
        self,
        intent: NoetriumUnit,
        effect: EffectReceipt,
    ) -> NoetriumUnit: ...


__all__ = ["EffectIntentOperationPort"]

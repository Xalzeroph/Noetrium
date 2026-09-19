from __future__ import annotations

from .audit import ArchitectureAudit, ComponentDescriptor


def build_platform_audit() -> ArchitectureAudit:
    """Declared cross-component authority policy.

    This is policy data, not a CLI concern.  Source-derived authority scanning is enforced
    separately; the declared model remains useful for capabilities/dataflow that cannot yet be
    inferred mechanically from syntax.
    """

    descriptors = (
        ComponentDescriptor(
            "platform.forensics",
            provides=("failure.forensics",),
            writes_states=("platform.failure_ledger",),
        ),
        ComponentDescriptor(
            "platform.model_os",
            provides=("model.serving",),
            writes_states=("platform.model_run",),
            side_effect_domains=("model_process",),
        ),
        ComponentDescriptor(
            "platform.prompt_os",
            provides=("prompt.runtime",),
            writes_states=("platform.prompt_generation",),
        ),
        ComponentDescriptor(
            "platform.telemetry",
            provides=("metrics.record",),
            writes_states=("platform.metrics",),
        ),
        ComponentDescriptor(
            "method.plugin",
            requires=("prompt.runtime", "metrics.record"),
            data_domains_read=("j_mem",),
            data_domains_write=("method_memory",),
        ),
    )
    return ArchitectureAudit(
        descriptors,
        state_owners={
            "platform.failure_ledger": "platform.forensics",
            "platform.model_run": "platform.model_os",
            "platform.prompt_generation": "platform.prompt_os",
            "platform.metrics": "platform.telemetry",
        },
        side_effect_owners={"model_process": "platform.model_os"},
        forbidden_dataflows={("j_audit", "method_memory"), ("j_eval", "method_memory")},
    )

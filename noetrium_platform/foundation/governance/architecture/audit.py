from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ComponentDescriptor:
    component_id: str
    provides: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    reads_states: tuple[str, ...] = ()
    writes_states: tuple[str, ...] = ()
    side_effect_domains: tuple[str, ...] = ()
    data_domains_read: tuple[str, ...] = ()
    data_domains_write: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AuditViolation:
    kind: str
    component_id: str
    detail: str


class ArchitectureAudit:
    def __init__(self, descriptors: tuple[ComponentDescriptor, ...], *, state_owners: dict[str, str],
                 side_effect_owners: dict[str, str], forbidden_dataflows: set[tuple[str, str]]) -> None:
        self.descriptors = descriptors
        self.state_owners = state_owners
        self.side_effect_owners = side_effect_owners
        self.forbidden_dataflows = forbidden_dataflows

    def run(self) -> tuple[AuditViolation, ...]:
        violations: list[AuditViolation] = []
        ids = {d.component_id for d in self.descriptors}
        if len(ids) != len(self.descriptors):
            violations.append(AuditViolation("duplicate_component", "*", "duplicate component id"))
        providers: dict[str, list[str]] = {}
        for d in self.descriptors:
            for cap in d.provides:
                providers.setdefault(cap, []).append(d.component_id)
            for state in d.writes_states:
                if self.state_owners.get(state) != d.component_id:
                    violations.append(AuditViolation("state_authority", d.component_id, f"writes {state} but owner={self.state_owners.get(state)}"))
            for effect in d.side_effect_domains:
                if self.side_effect_owners.get(effect) != d.component_id:
                    violations.append(AuditViolation("side_effect_authority", d.component_id, f"owns effect {effect} but registry={self.side_effect_owners.get(effect)}"))
            for src in d.data_domains_read:
                for dst in d.data_domains_write:
                    if (src, dst) in self.forbidden_dataflows:
                        violations.append(AuditViolation("forbidden_dataflow", d.component_id, f"{src}->{dst}"))
        for d in self.descriptors:
            for req in d.requires:
                if req not in providers:
                    violations.append(AuditViolation("missing_capability", d.component_id, req))
        return tuple(violations)

from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class DataflowEdge:
    source_component: str
    source_domain: str
    target_component: str
    target_domain: str
    purpose: str

class DataflowAudit:
    def __init__(self, edges: tuple[DataflowEdge,...], forbidden: set[tuple[str,str]]):
        self.edges=edges; self.forbidden=forbidden
    def run(self) -> tuple[str,...]:
        errors=[]
        for e in self.edges:
            if (e.source_domain,e.target_domain) in self.forbidden:
                errors.append(f"{e.source_component}:{e.source_domain}->{e.target_component}:{e.target_domain} ({e.purpose})")
        return tuple(errors)

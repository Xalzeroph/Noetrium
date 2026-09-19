from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from .registry import MetricRegistry


@dataclass(frozen=True, slots=True)
class MetricEmitterCoverage:
    emitted_metrics: tuple[str, ...]
    required_metrics: tuple[str, ...]
    errors: tuple[str, ...]


class MetricEmitterCoverageAudit:
    """Static audit of real `.observe(..., "metric.name", ...)` call sites."""

    def __init__(
        self,
        source_root: Path,
        registry: MetricRegistry,
        *,
        required_metrics: tuple[str, ...] = (),
    ) -> None:
        self.source_root=source_root
        self.registry=registry
        self.required_metrics=tuple(sorted(set(required_metrics)))

    @staticmethod
    def _metrics_in_file(path:Path)->set[str]:
        try:
            tree=ast.parse(path.read_text(encoding="utf-8"),filename=str(path))
        except (SyntaxError,UnicodeDecodeError):
            return set()
        found:set[str]=set()
        for node in ast.walk(tree):
            if not isinstance(node,ast.Call):
                continue
            func=node.func
            is_emitter=(isinstance(func,ast.Attribute) and func.attr in {"observe","_metric"}) or (isinstance(func,ast.Name) and func.id=="_metric")
            if not is_emitter:
                continue
            # Contextual store/wrapper: observe(context,name,value) or _metric(context,name,value).
            # Simple recorder: observe(name,value). Scan the first three literal arguments.
            candidates=node.args[:3]
            for arg in candidates:
                if isinstance(arg,ast.Constant) and isinstance(arg.value,str) and "." in arg.value:
                    found.add(arg.value)
        return found

    def run(self)->MetricEmitterCoverage:
        emitted:set[str]=set()
        for path in self.source_root.rglob("*.py"):
            if "__pycache__" in path.parts or "tests" in path.parts:
                continue
            emitted.update(self._metrics_in_file(path))
        errors=[]
        registered=set(self.registry.names())
        for metric in sorted(emitted-registered):
            errors.append(f"source emitter references unregistered metric: {metric}")
        for metric in self.required_metrics:
            if metric not in registered:
                errors.append(f"required metric is not registered: {metric}")
            elif metric not in emitted:
                errors.append(f"required metric has no real source emitter: {metric}")
        return MetricEmitterCoverage(tuple(sorted(emitted)),self.required_metrics,tuple(errors))

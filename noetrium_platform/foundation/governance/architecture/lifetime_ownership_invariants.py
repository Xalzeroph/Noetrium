from __future__ import annotations

import ast
from pathlib import Path

from .source_scan import SourceInvariantViolation, violation


def _class_node(path: Path, class_name: str) -> ast.ClassDef | None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    return None


def _method_node(class_node: ast.ClassDef, method_name: str) -> ast.FunctionDef | None:
    for node in class_node.body:
        if isinstance(node, ast.FunctionDef) and node.name == method_name:
            return node
    return None


def audit_lifetime_ownership_invariants(
    root: Path,
) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []

    authorities = (
        root / "noetrium_platform" / "composition" / "research_portfolio_execution.py"
    )
    if authorities.exists():
        text = authorities.read_text(encoding="utf-8")
        cls = _class_node(authorities, "ResearchExecutionAuthorities")
        if cls is None:
            rows.append(
                violation(
                    root,
                    authorities,
                    "lifetime_single_owner_authority",
                    1,
                    "ResearchExecutionAuthorities class is missing",
                )
            )
        else:
            close = _method_node(cls, "close")
            if close is not None:
                rows.append(
                    violation(
                        root,
                        authorities,
                        "lifetime_single_owner_authority",
                        close.lineno,
                        "ResearchExecutionAuthorities must expose retire(), never close()",
                    )
                )
            if _method_node(cls, "retire") is None:
                rows.append(
                    violation(
                        root,
                        authorities,
                        "lifetime_single_owner_authority",
                        cls.lineno,
                        "ResearchExecutionAuthorities must retire through resource-backed lifetime controller",
                    )
                )
        if "owned_runtime_resources" in text:
            line = text[: text.index("owned_runtime_resources")].count("\n") + 1
            rows.append(
                violation(
                    root,
                    authorities,
                    "lifetime_typed_owner_tokens",
                    line,
                    "raw closeable runtime owners are forbidden; use ResourceLifetimeRegistration",
                )
            )

    loader = (
        root
        / "noetrium_platform"
        / "composition"
        / "operator"
        / "project"
        / "project_research_loader.py"
    )
    if loader.exists():
        text = loader.read_text(encoding="utf-8")
        for forbidden in (
            "authorities.close()",
            "_execution_authorities.close()",
        ):
            if forbidden in text:
                line = text[: text.index(forbidden)].count("\n") + 1
                rows.append(
                    violation(
                        root,
                        loader,
                        "lifetime_authority_retirement_boundary",
                        line,
                        f"shared execution owner bypasses lifetime retire: {forbidden}",
                    )
                )
        cls = _class_node(loader, "LoadedResearchRoot")
        if cls is not None:
            close = _method_node(cls, "close")
            if close is None:
                rows.append(
                    violation(
                        root,
                        loader,
                        "lifetime_reverse_topological_shutdown",
                        cls.lineno,
                        "LoadedResearchRoot requires explicit reverse-topological close",
                    )
                )
            else:
                calls: list[tuple[str, int]] = []
                for item in ast.walk(close):
                    if not isinstance(item, ast.Call):
                        continue
                    func = item.func
                    if isinstance(func, ast.Attribute):
                        calls.append((func.attr, item.lineno))
                line_by_name: dict[str, int] = {}
                for name, line in sorted(calls, key=lambda row: row[1]):
                    line_by_name.setdefault(name, line)
                quiesce = line_by_name.get("quiesce_workloads")
                retire = line_by_name.get("retire")
                composition_close = tuple(
                    item.lineno
                    for item in ast.walk(close)
                    if isinstance(item, ast.Call)
                    and isinstance(item.func, ast.Attribute)
                    and item.func.attr == "close"
                    and isinstance(item.func.value, ast.Attribute)
                    and item.func.value.attr == "_composition"
                )
                if quiesce is None or retire is None or not composition_close:
                    rows.append(
                        violation(
                            root,
                            loader,
                            "lifetime_reverse_topological_shutdown",
                            close.lineno,
                            "LoadedResearchRoot close must quiesce, retire authorities, then close composition",
                        )
                    )
                elif not (quiesce < retire < min(composition_close)):
                    rows.append(
                        violation(
                            root,
                            loader,
                            "lifetime_reverse_topological_shutdown",
                            close.lineno,
                            "LoadedResearchRoot shutdown order must be quiesce -> retire -> composition close",
                        )
                    )

    return rows


__all__ = ["audit_lifetime_ownership_invariants"]

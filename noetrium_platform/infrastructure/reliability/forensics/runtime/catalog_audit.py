from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.infrastructure.reliability.failure.api import FailureCatalog


@dataclass(frozen=True, slots=True)
class FailureCatalogAuditReport:
    literal_build_failures: tuple[tuple[str,str,str,str], ...]
    literal_catalog_requires: tuple[tuple[str,str,str,str], ...]
    free_form_builder_calls: tuple[str, ...]
    errors: tuple[str, ...]


class FailureCatalogSourceAudit:
    """Checks literal failure taxonomy usage in production source against the central catalog."""

    def __init__(self, source_root: Path, catalog: FailureCatalog) -> None:
        self.source_root=source_root
        self.catalog=catalog

    @staticmethod
    def _literal_keywords(call: ast.Call) -> dict[str, str]:
        return {
            kw.arg: kw.value.value
            for kw in call.keywords
            if kw.arg is not None
            and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, str)
        }

    @staticmethod
    def _literal_args(call: ast.Call, count: int) -> tuple[str | None, ...]:
        return tuple(
            arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else None
            for arg in call.args[:count]
        )

    def run(self)->FailureCatalogAuditReport:
        builds=[]; requires=[]; free_form=[]; errors=[]
        for path in self.source_root.rglob('*.py'):
            if '__pycache__' in path.parts or 'tests' in path.parts:
                continue
            try: tree=ast.parse(path.read_text(encoding='utf-8'),filename=str(path))
            except (SyntaxError,UnicodeDecodeError): continue
            relative = path.relative_to(self.source_root)
            rel = str(relative)
            rel_posix = relative.as_posix()
            for node in ast.walk(tree):
                if not isinstance(node,ast.Call): continue
                func=node.func
                if isinstance(func,ast.Name) and func.id=='build_failure':
                    literals = self._literal_keywords(node)
                    d = literals.get('failure_domain')
                    c = literals.get('failure_code')
                    s = literals.get('stage')
                    if d and c and s:
                        builds.append((d,c,s,rel))
                        try:self.catalog.require(d,c,s)
                        except KeyError:errors.append(f'unregistered literal build_failure taxonomy: {(d,c,s)} at {rel}:{node.lineno}')
                    if rel_posix != 'infrastructure/reliability/failure/api/factory.py':
                        where=f'{rel}:{node.lineno}'
                        free_form.append(where)
                        errors.append(f'free-form build_failure bypasses FailureSpec authority at {where}')
                if isinstance(func,ast.Attribute) and func.attr=='require' and len(node.args)>=3:
                    vals = self._literal_args(node, 3)
                    if all(vals):
                        d,c,s=vals
                        requires.append((d,c,s,rel))
                        try:self.catalog.require(d,c,s)
                        except KeyError:errors.append(f'unregistered catalog require taxonomy: {(d,c,s)} at {rel}:{node.lineno}')
        return FailureCatalogAuditReport(
            tuple(sorted(builds)),
            tuple(sorted(requires)),
            tuple(sorted(free_form)),
            tuple(sorted(errors)),
        )

from __future__ import annotations

import re
from dataclasses import replace

from noetrium_platform.foundation.governance.algorithm.api import (
    AlgorithmLanguage,
    AlgorithmMetrics,
    AlgorithmSymbol,
    FileAnalysis,
    SourceDocument,
)
from .scoring import estimated_complexity, score_metrics

_JS_FUNC = re.compile(r"(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>|([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{")
_SHELL_FUNC = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{")
_JS_NON_FUNCTION_KEYWORDS = {"if", "for", "while", "switch", "catch", "with", "else", "do", "try"}
_JS_LOOP = re.compile(r"\b(for|while)\s*\(")
_JS_FOR_OF = re.compile(r"\bfor\s*\([^)]*\bof\s+(.+?)\)\s*\{")
_JS_CONST_ARRAY = re.compile(r"\bconst\s+([A-Za-z_$][\w$]*)\s*=\s*\[")


def _balanced_block(lines: list[str], start: int, open_char: str = "{", close_char: str = "}") -> int:
    depth = 0
    seen = False
    for idx in range(start, len(lines)):
        line = lines[idx]
        depth += line.count(open_char)
        if line.count(open_char):
            seen = True
        depth -= line.count(close_char)
        if seen and depth <= 0:
            return idx
    return len(lines) - 1


def _javascript_statically_bounded_iterable(expression: str, bounded_names: set[str]) -> bool:
    candidate = expression.strip()
    if candidate.startswith("["):
        return True
    return candidate in bounded_names


def _javascript_symbol_metrics(body: list[str]) -> tuple[int, int, int, int, int, int, int]:
    """Return structural JS metrics with loop depth independent from brace depth.

    Nested function bodies are independent symbols and are skipped. Constant
    literal iterables do not contribute asymptotic loop depth. Unknown loop
    bounds remain conservatively input-sized.
    """
    loops = 0
    max_loop_depth = 0
    io_in_loop = 0
    sort_calls = 0
    calls = 0
    branches = 0
    bounded_names: set[str] = set()
    frames: list[bool] = []
    skip_until = -1
    idx = 0
    while idx < len(body):
        raw = body[idx]
        line = raw.strip()
        if idx <= skip_until:
            idx += 1
            continue
        if idx > 0:
            nested = _JS_FUNC.search(raw)
            if nested:
                name = next((value for value in nested.groups() if value), "anonymous")
                if name not in _JS_NON_FUNCTION_KEYWORDS:
                    skip_until = _balanced_block(body, idx)
                    idx += 1
                    continue
        for match in _JS_CONST_ARRAY.finditer(raw):
            bounded_names.add(match.group(1))

        leading_closes = len(line) - len(line.lstrip("}"))
        for _ in range(min(leading_closes, len(frames))):
            frames.pop()
        active_unbounded = sum(frames)

        loop_match = _JS_LOOP.search(line)
        bounded_loop = False
        if loop_match:
            loops += 1
            for_of = _JS_FOR_OF.search(line)
            if for_of:
                bounded_loop = _javascript_statically_bounded_iterable(for_of.group(1), bounded_names)
            if not bounded_loop:
                active_unbounded += 1
                max_loop_depth = max(max_loop_depth, active_unbounded)

        calls += line.count("(")
        sort_calls += line.count(".sort(") + line.count(" sort ")
        if active_unbounded and re.search(r"\b(fs\.|fetch\(|axios\.|child_process\.)", line):
            io_in_loop += 1
        branches += sum(line.count(token) for token in ("if ", "if(", "case ", "?", "catch"))

        opens = line.count("{")
        closes = max(0, line.count("}") - leading_closes)
        loop_frame_available = loop_match is not None and not bounded_loop
        for open_index in range(opens):
            frames.append(loop_frame_available and open_index == 0)
        for _ in range(min(closes, len(frames))):
            frames.pop()
        idx += 1
    return loops, max_loop_depth, io_in_loop, sort_calls, calls, branches, sum(frames)


def _build_symbol(document: SourceDocument, name: str, start: int, end: int, body: list[str], language: AlgorithmLanguage) -> AlgorithmSymbol:
    if language == AlgorithmLanguage.JAVASCRIPT:
        loops, max_depth, io_in_loop, sort_calls, calls, branches, _ = _javascript_symbol_metrics(body)
        subprocess_in_loop = 0
    else:
        loop_tokens = ("for ", "while ", "until ", "select ")
        branch_tokens = ("if ", "case ", "&&", "||")
        loops = 0
        max_depth = 0
        depth = 0
        subprocess_in_loop = 0
        io_in_loop = 0
        sort_calls = 0
        calls = 0
        for raw in body:
            line = raw.strip()
            opens_loop = any(token in line for token in loop_tokens)
            if opens_loop:
                loops += 1
                depth += 1
                max_depth = max(max_depth, depth)
            calls += line.count("(")
            sort_calls += line.count(".sort(") + line.count(" sort ")
            if depth and re.search(r"(^|[;&|]\s*)(curl|wget|python|node|java|docker|git|ssh|scp|rsync|find|tar|unzip)\b", line):
                subprocess_in_loop += 1
            if re.match(r"^(done|fi|esac)\b", line):
                depth = max(0, depth - 1)
        branches = sum(sum(line.count(token) for token in branch_tokens) for line in body)
    base = AlgorithmMetrics(
        source_lines=max(1, end - start + 1),
        branches=branches,
        loops=loops,
        max_loop_depth=max_depth,
        sort_calls=sort_calls,
        io_calls_in_loops=io_in_loop,
        subprocess_calls_in_loops=subprocess_in_loop,
        call_count=calls,
        cyclomatic_estimate=1 + branches + loops,
        estimated_complexity=estimated_complexity(loops=(1 if max_depth else 0), max_loop_depth=max_depth, sort_calls=sort_calls, recursive_calls=0),
    )
    score, findings = score_metrics(base)
    return AlgorithmSymbol(
        symbol_id=f"{document.relative_path}::{name}",
        relative_path=document.relative_path,
        language=language,
        qualified_name=name,
        line_start=start + 1,
        line_end=end + 1,
        metrics=replace(base, risk_score=score),
        findings=findings,
    )


class JavaScriptAlgorithmAnalyzer:
    language = AlgorithmLanguage.JAVASCRIPT
    revision = "javascript-structural-v3"

    def analyze(self, document: SourceDocument) -> FileAnalysis:
        lines = document.text.splitlines()
        symbols: list[AlgorithmSymbol] = []
        seen: set[tuple[str, int]] = set()
        for idx, line in enumerate(lines):
            match = _JS_FUNC.search(line)
            if not match:
                continue
            name = next((value for value in match.groups() if value), "anonymous")
            if name in _JS_NON_FUNCTION_KEYWORDS:
                continue
            key = (name, idx)
            if key in seen:
                continue
            seen.add(key)
            end = _balanced_block(lines, idx)
            symbols.append(_build_symbol(document, name, idx, end, lines[idx:end + 1], self.language))
        return FileAnalysis(document.relative_path, document.language, document.sha256, self.revision, tuple(symbols), 0)


class ShellAlgorithmAnalyzer:
    language = AlgorithmLanguage.SHELL
    revision = "shell-structural-v2"

    def analyze(self, document: SourceDocument) -> FileAnalysis:
        lines = document.text.splitlines()
        symbols: list[AlgorithmSymbol] = []
        for idx, line in enumerate(lines):
            match = _SHELL_FUNC.match(line)
            if not match:
                continue
            end = _balanced_block(lines, idx)
            symbols.append(_build_symbol(document, match.group(1), idx, end, lines[idx:end + 1], self.language))
        return FileAnalysis(document.relative_path, document.language, document.sha256, self.revision, tuple(symbols), 0)


__all__ = ["JavaScriptAlgorithmAnalyzer", "ShellAlgorithmAnalyzer"]

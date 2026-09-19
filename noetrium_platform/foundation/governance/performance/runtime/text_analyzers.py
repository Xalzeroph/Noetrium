from __future__ import annotations

import re

from noetrium_platform.foundation.governance.performance.api import (
    PerformanceDocument, PerformanceFileAnalysis, PerformanceFinding, PerformanceHotspot,
    PerformanceLanguage, PerformanceMetrics, PerformancePriority,
)


class _TextPerformanceAnalyzer:
    language: PerformanceLanguage
    revision: str
    _blocking: tuple[str, ...] = ()

    def analyze(self, document: PerformanceDocument) -> PerformanceFileAnalysis:
        text = document.text
        findings: list[PerformanceFinding] = []
        score = 0
        io_loop = len(re.findall(r"(?:for|while)[^{\n]*[\s\S]{0,500}(?:readFileSync|writeFileSync|curl|wget)", text))
        fanout = len(re.findall(r"Promise\.all\s*\([^)]*\.map\s*\(", text)) if self.language is PerformanceLanguage.JAVASCRIPT else 0
        blocking = sum(text.count(token) for token in self._blocking)
        if fanout:
            score += 18 * fanout; findings.append(PerformanceFinding(PerformancePriority.P1, "unbounded-fanout", "Promise.all(map(...)) has no explicit concurrency bound", min(score,100)))
        if io_loop:
            score += 10 * io_loop; findings.append(PerformanceFinding(PerformancePriority.P2, "io-in-loop", "blocking/external I/O appears in loop-shaped source", min(score,100)))
        if blocking >= 2:
            score += 5 * blocking; findings.append(PerformanceFinding(PerformancePriority.P2, "sync-io-density", "multiple synchronous I/O/process calls in one script unit", min(score,100)))
        if not findings:
            return PerformanceFileAnalysis(document.relative_path, document.language, document.sha256, self.revision, (), 0)
        metrics = PerformanceMetrics(io_calls_in_loops=io_loop, unbounded_fanout_calls=fanout, io_calls=blocking, risk_score=min(score,100))
        return PerformanceFileAnalysis(document.relative_path, document.language, document.sha256, self.revision, (
            PerformanceHotspot(document.relative_path, document.relative_path, document.language, "<module>", 1, text.count("\n")+1, metrics, tuple(findings)),
        ), 0)


class JavaScriptPerformanceAnalyzer(_TextPerformanceAnalyzer):
    language = PerformanceLanguage.JAVASCRIPT
    revision = "javascript-performance-text-v1"
    _blocking = ("readFileSync(", "writeFileSync(", "execSync(", "spawnSync(")


class ShellPerformanceAnalyzer(_TextPerformanceAnalyzer):
    language = PerformanceLanguage.SHELL
    revision = "shell-performance-text-v1"
    _blocking = ("curl ", "wget ", "sleep ", "java ", "python ", "node ")

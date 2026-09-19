from __future__ import annotations

import re

from noetrium_platform.foundation.governance.concurrency.api import (
    ConcurrencyDocument, ConcurrencyFileAnalysis, ConcurrencyFinding, ConcurrencyHotspot,
    ConcurrencyLanguage, ConcurrencyMetrics, ConcurrencyPriority,
)


class JavaScriptConcurrencyAnalyzer:
    language = ConcurrencyLanguage.JAVASCRIPT
    revision = "javascript-concurrency-text-v1"
    def analyze(self, document: ConcurrencyDocument) -> ConcurrencyFileAnalysis:
        async_count = len(re.findall(r"\basync\s+(?:function\s+)?[A-Za-z_$]", document.text))
        await_count = len(re.findall(r"\bawait\b", document.text))
        promise_all = len(re.findall(r"\bPromise\.(?:all|allSettled|race|any)\s*\(", document.text))
        findings: list[ConcurrencyFinding] = []
        if re.search(r"Promise\.all\s*\(\s*\w+\.map\s*\(", document.text):
            findings.append(ConcurrencyFinding(ConcurrencyPriority.P1, "unbounded-promise-fanout", "Promise.all over map has no visible concurrency bound", 1))
        metrics = ConcurrencyMetrics(async_functions=async_count, await_calls=await_count, task_creations=promise_all)
        hotspots = () if not (async_count or await_count or findings) else (
            ConcurrencyHotspot(f"{document.relative_path}::<module>", document.relative_path, document.language, "<module>", 1, max(1, document.text.count("\n") + 1), metrics, tuple(findings)),
        )
        return ConcurrencyFileAnalysis(document.relative_path, document.language, document.sha256, self.revision, hotspots, 0)


class ShellConcurrencyAnalyzer:
    language = ConcurrencyLanguage.SHELL
    revision = "shell-concurrency-text-v2"
    def analyze(self, document: ConcurrencyDocument) -> ConcurrencyFileAnalysis:
        background = len(re.findall(r"(?:^|\s)&(?:\s|$)", document.text, flags=re.MULTILINE))
        wait_calls = len(re.findall(r"(?:^|[;\s])wait(?:\s|$)", document.text))
        findings: list[ConcurrencyFinding] = []
        detached_daemon = (
            "Concurrency-Policy: DETACHED_DAEMON" in document.text
            and "Concurrency-Rationale:" in document.text
            and "--pidfile" in document.text
        )
        if background and not wait_calls and not detached_daemon:
            findings.append(ConcurrencyFinding(ConcurrencyPriority.P1, "unowned-shell-background-job", "background shell jobs have no visible wait/join or explicit detached-daemon ownership contract", 1))
        metrics = ConcurrencyMetrics(task_creations=background, lifecycle_join_calls=wait_calls)
        hotspots = () if not (background or wait_calls or findings) else (
            ConcurrencyHotspot(f"{document.relative_path}::<script>", document.relative_path, document.language, "<script>", 1, max(1, document.text.count("\n") + 1), metrics, tuple(findings)),
        )
        return ConcurrencyFileAnalysis(document.relative_path, document.language, document.sha256, self.revision, hotspots, 0)

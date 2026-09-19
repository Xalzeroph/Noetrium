from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


def test_algorithm_baseline_cli_routes_historical_revision(monkeypatch, tmp_path: Path) -> None:
    import noetrium_platform.foundation.governance.algorithm.cli as cli

    calls = {}
    class Service:
        def accept_baseline(self, *, source_revision=None):
            calls["source_revision"] = source_revision
            return SimpleNamespace(symbols=(), candidate_count=0)
    def build(root, *, exact=False, git_executable=None):
        calls.update(root=root, exact=exact, git_executable=git_executable)
        return Service()
    monkeypatch.setattr(cli, "build_algorithm_governance", build)
    revision = "1" * 40
    assert cli.main(["baseline", "--root", str(tmp_path), "--source-revision", revision, "--git-executable", "git-test"]) == 0
    assert calls == {"root": tmp_path.resolve(), "exact": True, "git_executable": "git-test", "source_revision": revision}


def test_concurrency_baseline_cli_routes_historical_revision(monkeypatch, tmp_path: Path) -> None:
    import noetrium_platform.foundation.governance.concurrency.cli as cli

    calls = {}
    class Service:
        def accept_baseline(self, *, source_revision=None):
            calls["source_revision"] = source_revision
            return SimpleNamespace(hotspots=(), blocker_count=0)
    def build(root, *, exact=False, git_executable=None):
        calls.update(root=root, exact=exact, git_executable=git_executable)
        return Service()
    monkeypatch.setattr(cli, "build_concurrency_governance", build)
    revision = "2" * 40
    assert cli.main(["baseline", "--root", str(tmp_path), "--source-revision", revision, "--git-executable", "git-test"]) == 0
    assert calls == {"root": tmp_path.resolve(), "exact": True, "git_executable": "git-test", "source_revision": revision}


def test_performance_baseline_cli_routes_historical_revision(monkeypatch, tmp_path: Path) -> None:
    import noetrium_platform.foundation.governance.performance.cli as cli

    calls = {}
    class Service:
        def accept_baseline(self, *, source_revision=None):
            calls["source_revision"] = source_revision
            return SimpleNamespace(hotspots=(), blocker_count=0)
    def build(root, *, exact=False, git_executable=None):
        calls.update(root=root, exact=exact, git_executable=git_executable)
        return Service()
    monkeypatch.setattr(cli, "build_performance_governance", build)
    revision = "3" * 40
    assert cli.main(["baseline", "--root", str(tmp_path), "--source-revision", revision, "--git-executable", "git-test"]) == 0
    assert calls == {"root": tmp_path.resolve(), "exact": True, "git_executable": "git-test", "source_revision": revision}

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from tempfile import TemporaryDirectory

from noetrium_platform.foundation.governance.algorithm.api import AlgorithmLanguage, SourceDocument
from noetrium_platform.foundation.governance.api import (
    RepositorySourceFailureKind,
    RepositorySourceIncompleteError,
)
from noetrium_platform.foundation.governance.algorithm.providers import (
    FilesystemAlgorithmSnapshotStore,
    FilesystemFileAnalysisCache,
    RepositorySourceInventory,
)
from noetrium_platform.foundation.governance.providers import RepositorySourceTree
from noetrium_platform.foundation.governance.algorithm.runtime import (
    AlgorithmGovernanceService,
    AlgorithmScanner,
    JavaScriptAlgorithmAnalyzer,
    PythonAlgorithmAnalyzer,
    ShellAlgorithmAnalyzer,
    gate_against_baseline,
)


def _doc(text: str, language: AlgorithmLanguage = AlgorithmLanguage.PYTHON, path: str = "x.py") -> SourceDocument:
    import hashlib
    return SourceDocument(path, language, hashlib.sha256(text.encode()).hexdigest(), text)


def test_role01_capability_composition_hotspots_preserve_reviewed_complexity() -> None:
    root = Path(__file__).resolve().parents[1]
    analyzer = PythonAlgorithmAnalyzer()
    cases = (
        (
            "noetrium_platform/foundation/governance/architecture/api/capability_composition.py",
            "interface_contract_digest",
            "O(N log N)",
        ),
        (
            "noetrium_platform/foundation/governance/architecture/runtime/capability_composition.py",
            "CapabilityCompositionPlanner._index_offers",
            "O(N)",
        ),
        (
            "noetrium_platform/foundation/governance/architecture/runtime/capability_composition.py",
            "CapabilityCompositionPlanner._candidates",
            "O(N)",
        ),
    )
    for relative, qualified_name, expected in cases:
        text = (root / relative).read_text(encoding="utf-8")
        analysis = analyzer.analyze(_doc(text, path=relative))
        symbol = next(row for row in analysis.symbols if row.qualified_name == qualified_name)
        assert symbol.metrics.estimated_complexity == expected
        assert not any(row.priority.value == "P1" for row in symbol.findings)


def test_python_analyzer_detects_nested_loop_db_without_false_subprocess_recursion() -> None:
    source = '''\ndef run(rows, connection):\n    for row in rows:\n        connection.execute("SELECT 1")\n        subprocess.run(["true"])\n    return rows\n'''
    symbol = PythonAlgorithmAnalyzer().analyze(_doc(source)).symbols[0]
    assert symbol.metrics.max_loop_depth == 1
    assert symbol.metrics.database_calls_in_loops == 1
    assert symbol.metrics.recursive_calls == 0



def test_comprehension_iterable_database_call_is_setup_not_loop_amplification() -> None:
    source = """
def columns(connection):
    return {str(row[1]) for row in connection.execute("PRAGMA table_info(t)").fetchall()}
"""
    symbol = PythonAlgorithmAnalyzer().analyze(_doc(source)).symbols[0]
    assert symbol.metrics.max_loop_depth == 1
    assert symbol.metrics.database_calls_in_loops == 0


def test_later_comprehension_iterable_is_counted_inside_preceding_generator() -> None:
    source = """
def rows(groups, connection):
    return [row for group in groups for row in connection.execute("SELECT * FROM t WHERE k=?", (group,))]
"""
    symbol = PythonAlgorithmAnalyzer().analyze(_doc(source)).symbols[0]
    assert symbol.metrics.max_loop_depth == 2
    assert symbol.metrics.database_calls_in_loops == 1

def test_parent_function_does_not_count_nested_function_body() -> None:
    source = '''\ndef outer():\n    def inner(rows):\n        for a in rows:\n            for b in rows:\n                pass\n    return 1\n'''
    symbols = PythonAlgorithmAnalyzer().analyze(_doc(source)).symbols
    by_name = {s.qualified_name: s for s in symbols}
    assert by_name["outer"].metrics.loops == 0
    assert by_name["outer.inner"].metrics.max_loop_depth == 2


def test_javascript_keywords_are_not_reported_as_functions() -> None:
    source = '''\nfunction work(rows) {\n  for (const row of rows) {\n    if (row.ok) { console.log(row); }\n  }\n}\n'''
    symbols = JavaScriptAlgorithmAnalyzer().analyze(_doc(source, AlgorithmLanguage.JAVASCRIPT, "x.js")).symbols
    assert [s.qualified_name for s in symbols] == ["work"]


def test_javascript_brace_nesting_does_not_multiply_one_entity_scan() -> None:
    source = """
function findNearbyDroppedItem (entities) {
  let nearest = null
  for (const entity of Object.values(entities)) {
    if (!entity) continue
    if (entity.distance > 6) continue
    if (entity.score < 2) {
      nearest = entity
    }
  }
  return nearest
}
"""
    symbol = JavaScriptAlgorithmAnalyzer().analyze(
        _doc(source, AlgorithmLanguage.JAVASCRIPT, "runtime.js")
    ).symbols[0]
    assert symbol.metrics.loops == 1
    assert symbol.metrics.max_loop_depth == 1
    assert symbol.metrics.estimated_complexity == "O(N)"
    assert not any(f.code in {"nested-loop", "deep-nested-loop"} for f in symbol.findings)


def test_javascript_nested_callback_loop_is_an_independent_symbol() -> None:
    source = """
function captureItemDropNear (entities) {
  const onDrop = entity => {
    if (!entity) return
  }
  const pickupTarget = () => {
    let nearest = null
    for (const entity of Object.values(entities)) {
      if (!entity) continue
      nearest = entity
    }
    return nearest
  }
  return { onDrop, pickupTarget }
}
"""
    symbols = JavaScriptAlgorithmAnalyzer().analyze(
        _doc(source, AlgorithmLanguage.JAVASCRIPT, "runtime.js")
    ).symbols
    by_name = {symbol.qualified_name: symbol for symbol in symbols}
    assert by_name["captureItemDropNear"].metrics.max_loop_depth == 0
    assert by_name["captureItemDropNear"].metrics.estimated_complexity == "O(1)"
    assert by_name["pickupTarget"].metrics.max_loop_depth == 1
    assert by_name["pickupTarget"].metrics.estimated_complexity == "O(N)"


def test_javascript_fixed_literal_offset_mask_is_constant_factor() -> None:
    source = """
function nearby (entities) {
  let count = 0
  for (const entity of entities) {
    for (const dx of [-1, 0, 1]) {
      for (const dz of [-1, 0, 1]) {
        if (entity.x === dx && entity.z === dz) count += 1
      }
    }
  }
  return count
}
"""
    symbol = JavaScriptAlgorithmAnalyzer().analyze(
        _doc(source, AlgorithmLanguage.JAVASCRIPT, "runtime.js")
    ).symbols[0]
    assert symbol.metrics.loops == 3
    assert symbol.metrics.max_loop_depth == 1
    assert symbol.metrics.estimated_complexity == "O(N)"
    assert not any(f.code in {"nested-loop", "deep-nested-loop"} for f in symbol.findings)


def test_python_fixed_percentile_positions_do_not_create_database_amplification() -> None:
    source = """
def summarize(db, count):
    positions = {
        q: (0, 1, q)
        for q in (0.50, 0.95, 0.99)
    }
    required = sorted({
        position
        for low, high, _fraction in positions.values()
        for position in (low, high)
    })
    selected = {}
    for position in required:
        selected[position] = db.execute("SELECT value LIMIT 1 OFFSET ?", (position,)).fetchone()
    return selected
"""
    symbol = PythonAlgorithmAnalyzer().analyze(_doc(source)).symbols[0]
    assert symbol.metrics.loops == 4
    assert symbol.metrics.max_loop_depth == 0
    assert symbol.metrics.database_calls_in_loops == 0
    assert symbol.metrics.estimated_complexity == "O(1)"
    assert not any(f.code == "database-in-loop" for f in symbol.findings)


def test_python_unknown_cardinality_database_loop_still_fails_closed() -> None:
    source = """
def lookup(rows, db):
    for row in rows:
        db.execute("SELECT value WHERE id=?", (row,)).fetchone()
"""
    symbol = PythonAlgorithmAnalyzer().analyze(_doc(source)).symbols[0]
    assert symbol.metrics.max_loop_depth == 1
    assert symbol.metrics.database_calls_in_loops == 2
    assert any(f.code == "database-in-loop" and f.priority.value == "P1" for f in symbol.findings)


def test_shell_loop_external_process_is_detected() -> None:
    source = '''\nwork() {\n  for item in "$@"; do\n    curl "$item"\n  done\n}\n'''
    symbol = ShellAlgorithmAnalyzer().analyze(_doc(source, AlgorithmLanguage.SHELL, "x.sh")).symbols[0]
    assert symbol.metrics.subprocess_calls_in_loops >= 1


def test_repository_inventory_excludes_tests_by_default() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "pkg").mkdir()
        (root / "tests").mkdir()
        (root / "pkg" / "a.py").write_text("def a(): pass\n")
        (root / "tests" / "test_a.py").write_text("def test_a(): pass\n")
        docs = tuple(RepositorySourceInventory(RepositorySourceTree(root)).documents())
        assert [d.relative_path for d in docs] == ["pkg/a.py"]


def test_file_cache_is_content_and_revision_keyed() -> None:
    with TemporaryDirectory() as td:
        cache = FilesystemFileAnalysisCache(Path(td))
        analyzer = PythonAlgorithmAnalyzer()
        doc = _doc("def f(): return 1\n")
        analysis = analyzer.analyze(doc)
        cache.put(analysis)
        assert cache.get(doc.relative_path, doc.sha256, analyzer.revision) == analysis
        assert cache.get(doc.relative_path, "0" * 64, analyzer.revision) is None
        assert cache.get(doc.relative_path, doc.sha256, analyzer.revision + "-new") is None


def test_gate_blocks_complexity_regression() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.py").write_text("def f(rows):\n    return len(rows)\n")
        store = FilesystemAlgorithmSnapshotStore(root / "state")
        scanner = AlgorithmScanner(inventory=RepositorySourceInventory(RepositorySourceTree(root)), analyzers=(PythonAlgorithmAnalyzer(),))
        service = AlgorithmGovernanceService(scanner, store)
        baseline = service.accept_baseline()
        (root / "a.py").write_text("def f(rows):\n    for a in rows:\n        for b in rows:\n            pass\n")
        current = service.scan()
        report = gate_against_baseline(baseline, current)
        assert not report.passed
        assert any("complexity regression" in row for row in report.blockers)


def test_complexity_contract_preserves_structural_depth_without_false_high_priority_finding() -> None:
    source = '''\ndef hierarchical(groups):\n    """Algorithm-Complexity: O(N)\n    Algorithm-Rationale: N is the total number of child elements across disjoint groups, so nested syntax is not Cartesian multiplication.\n    """\n    out = []\n    for group in groups:\n        for item in group:\n            out.append(item)\n    return out\n'''
    symbol = PythonAlgorithmAnalyzer().analyze(_doc(source)).symbols[0]
    assert symbol.metrics.max_loop_depth == 2
    assert symbol.metrics.estimated_complexity == "O(N)"
    assert not any(f.priority.value in {"P0", "P1"} for f in symbol.findings)
    assert any(f.code == "complexity-contract" for f in symbol.findings)


def test_first_comprehension_iterable_database_call_is_not_counted_inside_loop() -> None:
    source = '''\ndef columns(conn):\n    return {row[1] for row in conn.execute("PRAGMA table_info(x)").fetchall()}\n'''
    symbol = PythonAlgorithmAnalyzer().analyze(_doc(source)).symbols[0]
    assert symbol.metrics.loops == 1
    assert symbol.metrics.database_calls_in_loops == 0


def test_nested_comprehension_later_iterable_database_call_is_counted_inside_outer_loop() -> None:
    source = '''\ndef rows(groups, conn):\n    return [(group, row) for group in groups for row in conn.execute("SELECT 1").fetchall()]\n'''
    symbol = PythonAlgorithmAnalyzer().analyze(_doc(source)).symbols[0]
    assert symbol.metrics.max_loop_depth == 2
    assert symbol.metrics.database_calls_in_loops >= 1


def test_diff_recognizes_unique_algorithm_move_without_new_debt() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "old.py").write_text("def f(rows):\n    for row in rows:\n        pass\n")
        store = FilesystemAlgorithmSnapshotStore(root / "state")
        scanner = AlgorithmScanner(
            inventory=RepositorySourceInventory(RepositorySourceTree(root)),
            analyzers=(PythonAlgorithmAnalyzer(),),
        )
        service = AlgorithmGovernanceService(scanner, store)
        baseline = service.accept_baseline()
        (root / "new.py").write_text((root / "old.py").read_text())
        (root / "old.py").unlink()
        current = service.scan()
        report = gate_against_baseline(baseline, current)
        assert report.passed
        assert report.diff.added == ()
        assert report.diff.removed == ()
        assert report.diff.moved == (("old.py::f", "new.py::f"),)


def test_gate_requires_reviewed_baseline_when_analyzer_revision_changes() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.py").write_text("def f():\n    return 1\n")
        store = FilesystemAlgorithmSnapshotStore(root / "state")
        scanner = AlgorithmScanner(
            inventory=RepositorySourceInventory(RepositorySourceTree(root)),
            analyzers=(PythonAlgorithmAnalyzer(),),
        )
        service = AlgorithmGovernanceService(scanner, store)
        baseline = service.accept_baseline()
        current = replace(baseline, analyzer_revision=baseline.analyzer_revision + "-new")
        report = gate_against_baseline(baseline, current)
        assert not report.passed
        assert any("analyzer revision changed" in blocker for blocker in report.blockers)


def test_repository_inventory_excludes_local_server_state() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "pkg").mkdir()
        (root / ".server-state").mkdir()
        (root / "pkg" / "a.py").write_text("def a(): return 1\n", encoding="utf-8")
        (root / ".server-state" / "foreign.py").write_text("def foreign(): return 2\n", encoding="utf-8")
        docs = tuple(RepositorySourceInventory(RepositorySourceTree(root)).documents())
        assert [d.relative_path for d in docs] == ["pkg/a.py"]


def test_shared_repository_source_tree_prunes_before_domain_adaptation() -> None:
    import hashlib
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "src").mkdir()
        (root / "tests").mkdir()
        (root / "node_modules" / "deep").mkdir(parents=True)
        (root / "build").mkdir()
        (root / "src" / "z.py").write_text("Z = 1\n", encoding="utf-8")
        (root / "src" / "a.js").write_text("export const A = 1;\n", encoding="utf-8")
        (root / "z.py").write_text("ROOT = 1\n", encoding="utf-8")
        (root / "tests" / "test_z.py").write_text("def test_z(): pass\n", encoding="utf-8")
        (root / "node_modules" / "deep" / "foreign.py").write_text("BAD = 1\n", encoding="utf-8")
        (root / "build" / "generated.py").write_text("BAD = 2\n", encoding="utf-8")

        docs = tuple(RepositorySourceTree(root).documents(suffixes={".py", ".js"}))
        assert [doc.relative_path for doc in docs] == ["src/a.js", "src/z.py", "z.py"]
        source_bytes = (root / "src" / "z.py").read_bytes()
        source_doc = next(doc for doc in docs if doc.relative_path == "src/z.py")
        assert source_doc.sha256 == hashlib.sha256(source_bytes).hexdigest()
        assert source_doc.text == source_bytes.decode("utf-8")

        with_tests = tuple(RepositorySourceTree(root, include_tests=True).documents(suffixes={".py"}))
        assert [doc.relative_path for doc in with_tests] == ["src/z.py", "tests/test_z.py", "z.py"]


def test_algorithm_adapter_preserves_extra_exclusions_on_shared_snapshot() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "src").mkdir()
        (root / ".mypy_cache").mkdir()
        (root / "src" / "ok.py").write_text("OK = 1\n", encoding="utf-8")
        (root / ".mypy_cache" / "foreign.py").write_text("FOREIGN = 1\n", encoding="utf-8")

        snapshot = RepositorySourceTree(root).snapshot(suffixes={".py"})
        assert [doc.relative_path for doc in snapshot.documents(suffixes={".py"})] == [
            ".mypy_cache/foreign.py", "src/ok.py"
        ]
        algorithm_paths = [
            doc.relative_path for doc in RepositorySourceInventory(snapshot).documents()
        ]
        assert algorithm_paths == ["src/ok.py"]


def test_repository_source_snapshot_is_explicit_and_frozen() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.py").write_text("A = 1\n", encoding="utf-8")
        tree = RepositorySourceTree(root)
        snapshot = tree.snapshot(suffixes={".py"})
        (root / "b.py").write_text("B = 2\n", encoding="utf-8")

        assert [doc.relative_path for doc in snapshot.documents(suffixes={".py"})] == ["a.py"]
        assert [doc.relative_path for doc in tree.documents(suffixes={".py"})] == ["a.py", "b.py"]


def test_governance_builders_accept_one_shared_source_snapshot() -> None:
    from noetrium_platform.foundation.governance.algorithm.composition import build_algorithm_governance
    from noetrium_platform.foundation.governance.concurrency.composition import build_concurrency_governance
    from noetrium_platform.foundation.governance.performance.composition import build_performance_governance

    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "noetrium_platform").mkdir()
        (root / "noetrium_platform" / "x.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        snapshot = RepositorySourceTree(root).snapshot()
        algorithm = build_algorithm_governance(
            root, state_root=root / ".state-algorithm", source_inventory=snapshot
        ).scan(persist=False)
        concurrency = build_concurrency_governance(
            root, state_root=root / ".state-concurrency", source_inventory=snapshot
        ).scan(persist=False)
        performance = build_performance_governance(
            root, state_root=root / ".state-performance", source_inventory=snapshot
        ).scan(persist=False)

        assert algorithm.source_digest
        assert concurrency.source_digest
        assert performance.source_digest


def test_repository_source_tree_fails_closed_on_undecodable_source(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(RuntimeError, match="snapshot incomplete"):
        tuple(RepositorySourceTree(tmp_path).documents(suffixes={".py"}))


def test_repository_source_tree_reports_typed_utf8_failure(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(RepositorySourceIncompleteError) as caught:
        RepositorySourceTree(tmp_path).snapshot(suffixes={".py"})
    assert caught.value.failures == (
        caught.value.failures[0],
    )
    failure = caught.value.failures[0]
    assert failure.kind is RepositorySourceFailureKind.UTF8_DECODE
    assert failure.relative_path == "bad.py"


def test_repository_source_tree_fails_closed_on_directory_walk_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import noetrium_platform.foundation.governance.providers.repository_source as source_provider

    blocked = tmp_path / "blocked"
    def failing_walk(_root, *, topdown, onerror):
        assert topdown is True
        onerror(PermissionError(13, "denied", str(blocked)))
        return ()

    monkeypatch.setattr(source_provider.os, "walk", failing_walk)
    with pytest.raises(RepositorySourceIncompleteError) as caught:
        RepositorySourceTree(tmp_path).snapshot(suffixes={".py"})
    failure = caught.value.failures[0]
    assert failure.kind is RepositorySourceFailureKind.DIRECTORY_WALK
    assert failure.relative_path == "blocked"


def test_repository_source_tree_reports_typed_file_read_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import noetrium_platform.foundation.governance.providers.repository_source as source_provider

    target = tmp_path / "denied.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")
    original = source_provider.Path.read_bytes

    def denied(path: Path) -> bytes:
        if path == target:
            raise PermissionError(13, "denied", str(path))
        return original(path)

    monkeypatch.setattr(source_provider.Path, "read_bytes", denied)
    with pytest.raises(RepositorySourceIncompleteError) as caught:
        RepositorySourceTree(tmp_path).snapshot(suffixes={".py"})
    failure = caught.value.failures[0]
    assert failure.kind is RepositorySourceFailureKind.FILE_READ
    assert failure.relative_path == "denied.py"


def test_repository_source_index_fails_closed_on_python_parse_error(tmp_path: Path) -> None:
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    with pytest.raises(RepositorySourceIncompleteError) as caught:
        RepositorySourceTree(tmp_path).index(suffixes={".py"})
    failure = caught.value.failures[0]
    assert failure.kind is RepositorySourceFailureKind.PYTHON_PARSE
    assert failure.relative_path == "broken.py"


def test_repository_source_paths_use_canonical_posix_sorting(tmp_path: Path) -> None:
    for name in ("configs.py", "CURRENT_VALIDATION.py", "alpha.py", "Z.py"):
        (tmp_path / name).write_text("VALUE = 1\n", encoding="utf-8")
    paths = [
        blob.relative_path
        for blob in RepositorySourceTree(tmp_path).documents(suffixes={".py"})
    ]
    assert paths == sorted(paths)


def test_python_analyzer_reuses_canonical_source_index_ast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "a.py"
    target.write_text("def f():\n    return 1\n", encoding="utf-8")
    index = RepositorySourceTree(tmp_path).index(suffixes={".py"})
    document = next(iter(RepositorySourceInventory(index).documents()))

    import noetrium_platform.foundation.governance.algorithm.runtime.python_analyzer as analyzer_module
    monkeypatch.setattr(
        analyzer_module.ast,
        "parse",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("reparsed source")),
    )
    analysis = PythonAlgorithmAnalyzer(index).analyze(document)
    assert analysis.parse_errors == 0
    assert [symbol.qualified_name for symbol in analysis.symbols] == ["f"]


def test_repository_source_index_rejects_identity_drift(tmp_path: Path) -> None:
    target = tmp_path / "a.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")
    index = RepositorySourceTree(tmp_path).index(suffixes={".py"})
    with pytest.raises(ValueError, match="source identity mismatch"):
        index.text("a.py", sha256="0" * 64)

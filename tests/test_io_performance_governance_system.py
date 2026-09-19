from pathlib import Path
import tempfile
from noetrium_platform.foundation.governance.performance.composition import build_performance_governance

def test_performance_governance_detects_blocking_async_unbounded_queue_and_io_loop():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td); pkg=root/'noetrium_platform'; pkg.mkdir()
        (pkg/'x.py').write_text('''import asyncio, time\nasync def bad(xs):\n    q=asyncio.Queue()\n    time.sleep(1)\n    for x in xs:\n        open(str(x)).read()\n''',encoding='utf-8')
        snap=build_performance_governance(root).scan(persist=False)
        codes={f.code for h in snap.hotspots for f in h.findings}
        assert 'blocking-sleep-in-async' in codes
        assert 'unbounded-queue' in codes
        assert 'io-in-loop' in codes
        assert snap.blocker_count >= 2


def test_non_database_execute_method_is_not_misclassified_as_sql_roundtrip():
    from noetrium_platform.foundation.governance.performance.api import PerformanceDocument, PerformanceLanguage
    from noetrium_platform.foundation.governance.performance.runtime import PythonPerformanceAnalyzer
    import hashlib
    text = "def run(client, xs):\n    for x in xs:\n        client.execute(x)\n"
    doc=PerformanceDocument("x.py",PerformanceLanguage.PYTHON,hashlib.sha256(text.encode()).hexdigest(),text)
    result=PythonPerformanceAnalyzer().analyze(doc)
    assert all("database-roundtrip-in-loop" not in {f.code for f in h.findings} for h in result.hotspots)

def test_connection_execute_is_classified_as_database_roundtrip():
    from noetrium_platform.foundation.governance.performance.api import PerformanceDocument, PerformanceLanguage
    from noetrium_platform.foundation.governance.performance.runtime import PythonPerformanceAnalyzer
    import hashlib
    text = "def run(connection, xs):\n    for x in xs:\n        connection.execute('select 1')\n"
    doc=PerformanceDocument("x.py",PerformanceLanguage.PYTHON,hashlib.sha256(text.encode()).hexdigest(),text)
    result=PythonPerformanceAnalyzer().analyze(doc)
    assert any("database-roundtrip-in-loop" in {f.code for f in h.findings} for h in result.hotspots)

def test_for_iterable_io_is_not_counted_as_per_iteration_body_io():
    from noetrium_platform.foundation.governance.performance.api import PerformanceDocument, PerformanceLanguage
    from noetrium_platform.foundation.governance.performance.runtime import PythonPerformanceAnalyzer
    import hashlib
    text = "def chunks(handle):\n    for chunk in iter(lambda: handle.read(1024), b''):\n        pass\n"
    doc=PerformanceDocument("x.py",PerformanceLanguage.PYTHON,hashlib.sha256(text.encode()).hexdigest(),text)
    result=PythonPerformanceAnalyzer().analyze(doc)
    assert all("io-in-loop" not in {f.code for f in h.findings} for h in result.hotspots)


def test_performance_governance_accepts_explicit_rolling_fanout_window():
    from noetrium_platform.foundation.governance.performance.api import PerformanceDocument, PerformanceLanguage
    from noetrium_platform.foundation.governance.performance.runtime import PythonPerformanceAnalyzer
    import hashlib
    text = "def run(pending, group, workers):\n    active = []\n    while pending or active:\n        while pending and len(active) < workers:\n            active.append(group.submit(pending.pop()))\n        if active:\n            active.pop().result()\n"
    doc=PerformanceDocument("x.py",PerformanceLanguage.PYTHON,hashlib.sha256(text.encode()).hexdigest(),text)
    result=PythonPerformanceAnalyzer().analyze(doc)
    assert all("unbounded-fanout" not in {f.code for f in h.findings} for h in result.hotspots)


def test_performance_governance_rejects_submit_in_unbounded_loop():
    from noetrium_platform.foundation.governance.performance.api import PerformanceDocument, PerformanceLanguage
    from noetrium_platform.foundation.governance.performance.runtime import PythonPerformanceAnalyzer
    import hashlib
    text = "def run(xs, group):\n    handles = []\n    for x in xs:\n        handles.append(group.submit(x))\n"
    doc=PerformanceDocument("x.py",PerformanceLanguage.PYTHON,hashlib.sha256(text.encode()).hexdigest(),text)
    result=PythonPerformanceAnalyzer().analyze(doc)
    assert any("unbounded-fanout" in {f.code for f in h.findings} for h in result.hotspots)


def test_performance_inventory_excludes_local_server_state(tmp_path: Path) -> None:
    from noetrium_platform.foundation.governance.performance.providers import RepositoryPerformanceSourceInventory
    from noetrium_platform.foundation.governance.providers import RepositorySourceTree
    (tmp_path / "noetrium_platform").mkdir()
    (tmp_path / ".server-state").mkdir()
    (tmp_path / "noetrium_platform" / "ok.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / ".server-state" / "foreign.py").write_text("def f(xs):\n    for x in xs:\n        open(str(x)).read()\n", encoding="utf-8")
    paths = [doc.relative_path for doc in RepositoryPerformanceSourceInventory(RepositorySourceTree(tmp_path)).documents()]
    assert paths == ["noetrium_platform/ok.py"]

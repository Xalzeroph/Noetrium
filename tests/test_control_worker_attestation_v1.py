from pathlib import Path

from scripts import control_worker


def test_lifecycle_request_uses_worker_bound_root_set(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    roots = tmp_path / "roots.txt"
    roots.write_text(str(project) + "\n", encoding="utf-8")
    monkeypatch.setenv("NOETRIUM_CONTROL_PROJECT_ROOTS_FILE", str(roots))

    assert control_worker._project_roots(
        ("-c", "research-cli", "inspect", "--project", str(project))
    ) == (project,)

    # Request argv cannot override the root-set identity already fenced into
    # the resident worker generation.
    assert control_worker._project_roots(
        ("runner.py", "--project-roots-file", str(tmp_path / "foreign"))
    ) == (project,)


def test_source_drift_reports_exact_changed_file(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text("x = 1\n", encoding="utf-8")
    stat = source.stat()
    baseline = {str(source): (stat.st_mtime_ns, stat.st_size)}
    assert control_worker._source_drift(baseline) is None

    source.write_text("x = 12345\n", encoding="utf-8")
    drift = control_worker._source_drift(baseline)
    assert drift is not None
    assert drift[0] == str(source)
    assert drift[1] == baseline[str(source)]
    assert drift[2] != drift[1]

from __future__ import annotations

import io

import scripts.release_regression as regression


def test_release_diagnostics_are_safe_for_narrow_windows_console_codecs() -> None:
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="gbk", errors="strict", newline="")
    regression._write_diagnostic_output("pytest diagnostic: \ufffd 😀\n", stream=stream)
    stream.flush()
    rendered = raw.getvalue().decode("gbk")
    assert "pytest diagnostic:" in rendered
    assert "\\ufffd" in rendered
    assert "\\U0001f600" in rendered


def test_release_diagnostics_remain_exact_when_stream_can_encode_unicode() -> None:
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="utf-8", errors="strict", newline="")
    message = "pytest diagnostic: 中文 \ufffd 😀\n"
    regression._write_diagnostic_output(message, stream=stream)
    stream.flush()
    assert raw.getvalue().decode("utf-8") == message


def test_release_shard_uses_private_pytest_basetemp(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_run(root, args, *, timeout_seconds, result_path, **_kwargs):
        captured["root"] = root
        captured["args"] = tuple(args)
        captured["timeout_seconds"] = timeout_seconds
        captured["result_path"] = result_path
        result_path.write_text(
            '{"schema_version":1,"tests_collected":1,"passed":1,"skipped":0,'
            '"failed":0,"xfailed":0,"xpassed":0,"collection_errors":0,'
            '"deselected":0,"pytest_exitstatus":0,"duration_seconds":0.01,'
            '"file_durations_seconds":{}}',
            encoding="utf-8",
        )

    monkeypatch.setattr(regression, "_run_pytest", fake_run)
    evidence = regression._run_pytest_shard(tmp_path, ["-q", "tests/test_a.py"], timeout_seconds=7.0)
    args = captured["args"]
    assert isinstance(args, tuple)
    idx = args.index("--basetemp")
    basetemp = args[idx + 1]
    assert "release-pytest-result-" in basetemp
    assert basetemp.endswith("pytest")
    assert args[idx + 2 :] == ("-q", "tests/test_a.py")
    assert evidence.tests_collected == 1
    assert evidence.passed == 1

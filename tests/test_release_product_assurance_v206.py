from __future__ import annotations

import hashlib
import os

import scripts.product_assurance_gate as assurance


def _receipt(name: str, argv: list[str], returncode: int) -> assurance.GateCommandReceipt:
    empty = hashlib.sha256(b"").hexdigest()
    return assurance.GateCommandReceipt(
        name=name,
        argv=tuple(argv),
        returncode=returncode,
        stdout_sha256=empty,
        stderr_sha256=empty,
        stdout_tail="",
        stderr_tail="",
    )


def _bind_source_identity(monkeypatch) -> None:
    monkeypatch.setattr(
        assurance,
        "_source_identity",
        lambda: ("a" * 40, "role06", "b" * 64, True),
    )


def test_product_assurance_gate_fails_fast_on_blocker(monkeypatch):
    calls: list[str] = []
    def fake_run(name: str, argv: list[str]):
        calls.append(name)
        return _receipt(name, argv, 1 if name == "provider-conformance" else 0)

    monkeypatch.setattr(assurance, "_run", fake_run)
    _bind_source_identity(monkeypatch)
    result = assurance.evaluate(full=True)
    assert result.passed is False
    assert calls == ["test-taxonomy", "provider-conformance"]


def test_full_assurance_can_skip_architecture_gate(monkeypatch):
    commands: list[str] = []

    def fake_run(name: str, argv: list[str]):
        commands.append(name)
        return _receipt(name, argv, 0)

    monkeypatch.setattr(assurance, "_run", fake_run)
    _bind_source_identity(monkeypatch)
    result = assurance.evaluate(full=True, include_architecture=False)
    assert result.passed is True
    assert commands == ["test-taxonomy", "provider-conformance", "full-regression"]


def test_full_assurance_binds_source_and_uses_external_basetemp(monkeypatch):
    commands: list[tuple[str, list[str]]] = []

    def fake_run(name: str, argv: list[str]):
        commands.append((name, argv))
        return _receipt(name, argv, 0)

    monkeypatch.setattr(assurance, "_run", fake_run)
    _bind_source_identity(monkeypatch)
    result = assurance.evaluate(full=True)
    assert result.passed is True
    assert result.source_sha == "a" * 40
    assert result.branch == "role06"
    assert result.source_tree_sha256 == "b" * 64
    assert result.source_clean is True
    assert result.closing_source_sha == "a" * 40
    assert result.closing_branch == "role06"
    assert result.closing_source_tree_sha256 == "b" * 64
    assert result.closing_source_clean is True
    assert result.source_identity_rechecked is True
    assert result.source_identity_consistent is True
    assert [name for name, _ in commands] == [
        "test-taxonomy", "provider-conformance", "architecture", "full-regression",
    ]
    full_argv = commands[-1][1]
    index = full_argv.index("--basetemp")
    expected_temp_root = os.environ.get("RUNNER_TEMP", assurance.tempfile.gettempdir())
    assert str(expected_temp_root) in full_argv[index + 1]
    assert "noetrium-product-assurance-full" in full_argv[index + 1]


def test_full_assurance_blocks_dirty_source_before_commands(monkeypatch):
    monkeypatch.setattr(
        assurance,
        "_source_identity",
        lambda: ("c" * 40, "role06", "d" * 64, False),
    )
    monkeypatch.setattr(
        assurance,
        "_run",
        lambda name, argv: (_ for _ in ()).throw(AssertionError("commands must not run")),
    )
    result = assurance.evaluate(full=True)
    assert result.passed is False
    assert result.source_clean is False
    assert result.commands == ()


def test_product_assurance_rejects_closing_source_identity_drift(monkeypatch):
    identities = iter((
        ("a" * 40, "role06", "b" * 64, True),
        ("c" * 40, "role06", "d" * 64, True),
    ))
    monkeypatch.setattr(assurance, "_source_identity", lambda: next(identities))
    monkeypatch.setattr(assurance, "_run", lambda name, argv: _receipt(name, argv, 0))
    result = assurance.evaluate(full=False)
    assert result.passed is False
    assert result.source_identity_rechecked is True
    assert result.source_identity_consistent is False
    assert result.source_sha == "a" * 40
    assert result.closing_source_sha == "c" * 40
    assert result.source_tree_sha256 == "b" * 64
    assert result.closing_source_tree_sha256 == "d" * 64

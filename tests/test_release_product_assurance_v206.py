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
    assert calls == ["platform-compile", "public-contracts", "provider-conformance"]


def test_full_assurance_can_skip_architecture_gate(monkeypatch):
    commands: list[str] = []

    def fake_run(name: str, argv: list[str]):
        commands.append(name)
        return _receipt(name, argv, 0)

    monkeypatch.setattr(assurance, "_run", fake_run)
    _bind_source_identity(monkeypatch)
    result = assurance.evaluate(full=True, include_architecture=False)
    assert result.passed is True
    assert commands == [
        "platform-compile",
        "public-contracts",
        "provider-conformance",
        "no-degradation",
    ]


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
        "platform-compile",
        "public-contracts",
        "provider-conformance",
        "no-degradation",
        "architecture",
    ]
    architecture_argv = commands[-1][1]
    assert "noetrium_platform.foundation.governance.architecture.gate" in architecture_argv


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

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import scripts.verify_npe_cleanroom as npe


def _receipt(
    name: str,
    returncode: int,
    payload: dict | None = None,
    *,
    stdout: str | None = None,
) -> npe.CommandReceipt:
    text = stdout if stdout is not None else (
        json.dumps(payload) if payload is not None else ""
    )
    if returncode == 0:
        stdout_tail, stderr_tail = text, ""
    else:
        stdout_tail, stderr_tail = "", text
    return npe.CommandReceipt(
        name=name,
        argv=(name,),
        returncode=returncode,
        stdout_sha256=hashlib.sha256(stdout_tail.encode()).hexdigest(),
        stderr_sha256=hashlib.sha256(stderr_tail.encode()).hexdigest(),
        stdout_tail=stdout_tail[-4000:],
        stderr_tail=stderr_tail[-4000:],
        json_output=(
            text if npe._strict_json_object(text) is not None else None
        ),
    )


def _doctor(
    *,
    ready: bool,
    blocked: tuple[str, ...] = (),
) -> dict:
    checks = [
        {
            "check_id": "public_import_boundary",
            "disposition": "pass",
            "summary": "public",
            "remediation": "",
        },
    ]
    for check_id in blocked:
        checks.append(
            {
                "check_id": check_id,
                "disposition": "blocked",
                "summary": "blocked",
                "remediation": "fix",
            }
        )
    return {
        "ok": ready,
        "command": "project doctor",
        "result": {
            "project_root": "project",
            "template_revision": "noetrium.project-template.v10",
            "checks": checks,
        },
    }


def _identity(
    *,
    portfolio_digest: str = "2" * 64,
    program_digests: tuple[str, ...] = ("1" * 64, "4" * 64),
) -> dict:
    return {
        "portfolio_id": "npe-reference",
        "portfolio_digest": portfolio_digest,
        "programs": [
            {
                "program_id": f"paper-{index}",
                "program_digest": digest,
            }
            for index, digest in enumerate(program_digests, start=1)
        ],
    }


def _bind_fake_venv(monkeypatch) -> dict[str, Path]:
    state: dict[str, Path] = {}

    def create(root: Path) -> bool:
        state["root"] = Path(root)
        return True

    monkeypatch.setattr(npe, "_create_venv", create)
    return state


def test_json_output_uses_complete_machine_receipt_not_human_tail() -> None:
    payload = {"ok": True, "padding": "x" * 6000, "result": {"value": 7}}
    text = json.dumps(payload)
    receipt = _receipt("large", 0, stdout=text)
    assert len(receipt.stdout_tail) == 4000
    assert npe._json_output(receipt) == payload


def test_json_output_rejects_duplicate_keys_and_non_finite_constants() -> None:
    duplicate = _receipt(
        "duplicate",
        0,
        stdout='{ "ok": true, "ok": false }',
    )
    non_finite = _receipt(
        "nonfinite",
        0,
        stdout='{ "ok": true, "value": NaN }',
    )
    assert npe._json_output(duplicate) is None
    assert npe._json_output(non_finite) is None


def test_doctor_facts_preserve_public_boundary_and_v9_template() -> None:
    receipt = _receipt(
        "project-doctor",
        4,
        _doctor(ready=False, blocked=("standard_bindings",)),
    )
    ready, public_boundary, template, blockers = npe._doctor_facts(receipt)
    assert ready is False
    assert public_boundary is True
    assert template == "noetrium.project-template.v10"
    assert blockers == ("standard_bindings",)


def test_doctor_facts_fail_closed_on_invalid_json() -> None:
    receipt = _receipt("project-doctor", 4, stdout="not-json")
    assert npe._doctor_facts(receipt) == (
        False,
        False,
        None,
        ("DOCTOR_RECEIPT_INVALID",),
    )


def test_clean_room_reports_missing_venv_as_environment_blocker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "noetrium.whl"
    artifact.write_bytes(b"wheel")
    monkeypatch.setattr(npe, "_create_venv", lambda root: False)
    monkeypatch.setattr(
        npe,
        "_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("unexpected command")
        ),
    )

    result = npe.verify_npe_cleanroom(artifact)

    assert result.schema == "noetrium.npe-clean-room.v5"
    assert result.npe_verified is False
    assert result.blocker_codes == ("PYTHON_VENV_UNAVAILABLE",)
    assert result.commands == ()


def test_clean_room_records_doctor_blocker_without_false_pass(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "noetrium.whl"
    artifact.write_bytes(b"wheel")
    venv_state = _bind_fake_venv(monkeypatch)

    def fake_run(name, argv, cwd, env):
        del argv, cwd, env
        if name == "installed-metadata":
            module_file = (
                venv_state["root"]
                / "Lib"
                / "site-packages"
                / "noetrium"
                / "__init__.py"
            )
            return _receipt(
                name,
                0,
                {"version": "0.44.0", "module_file": str(module_file)},
            )
        rows = {
            "install-artifact": _receipt("install-artifact", 0),
            "project-create": _receipt(
                "project-create",
                0,
                {"ok": True},
            ),
            "project-doctor": _receipt(
                "project-doctor",
                4,
                _doctor(ready=False, blocked=("standard_bindings",)),
            ),
            "project-test": _receipt("project-test", 0, {"ok": True}),
        }
        return rows[name]

    monkeypatch.setattr(npe, "_run", fake_run)
    result = npe.verify_npe_cleanroom(artifact)

    assert result.npe_verified is False
    assert result.project_created is True
    assert result.generated_tests_passed is True
    assert result.public_import_boundary_passed is True
    assert result.research_portfolio_loaded is False
    assert "DOCTOR_BLOCKED:standard_bindings" in result.blocker_codes


def test_clean_room_verifies_research_identity_across_fresh_processes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "noetrium.whl"
    artifact.write_bytes(b"wheel")
    venv_state = _bind_fake_venv(monkeypatch)
    monkeypatch.setattr(
        npe,
        "_research_project_package",
        lambda project: "npe_reference",
    )

    def fake_run(name, argv, cwd, env):
        del argv, cwd, env
        if name == "installed-metadata":
            module_file = (
                venv_state["root"]
                / "Lib"
                / "site-packages"
                / "noetrium"
                / "__init__.py"
            )
            return _receipt(
                name,
                0,
                {"version": "0.44.0", "module_file": str(module_file)},
            )
        rows = {
            "install-artifact": _receipt("install-artifact", 0),
            "project-create": _receipt("project-create", 0, {"ok": True}),
            "project-doctor": _receipt(
                "project-doctor",
                0,
                _doctor(ready=True),
            ),
            "project-test": _receipt("project-test", 0, {"ok": True}),
            "research-portfolio-load-1": _receipt(
                "research-program-load-1",
                0,
                _identity(),
            ),
            "research-portfolio-load-2": _receipt(
                "research-program-load-2",
                0,
                _identity(),
            ),
        }
        return rows[name]

    monkeypatch.setattr(npe, "_run", fake_run)
    result = npe.verify_npe_cleanroom(artifact)

    assert result.schema == "noetrium.npe-clean-room.v5"
    assert result.doctor_ready is True
    assert result.research_portfolio_loaded is True
    assert result.fresh_process_identity_stable is True
    assert result.npe_verified is True
    assert result.blocker_codes == ()


def test_research_identity_accepts_multiple_programs() -> None:
    receipt = _receipt(
        "research-portfolio-load",
        0,
        _identity(program_digests=("1" * 64, "2" * 64, "3" * 64)),
    )
    facts = npe._research_identity_facts(receipt)
    assert facts is not None
    assert len(facts["programs"]) == 3


def test_clean_room_rejects_fresh_process_research_identity_drift(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "noetrium.whl"
    artifact.write_bytes(b"wheel")
    venv_state = _bind_fake_venv(monkeypatch)
    monkeypatch.setattr(
        npe,
        "_research_project_package",
        lambda project: "npe_reference",
    )

    def fake_run(name, argv, cwd, env):
        del argv, cwd, env
        if name == "installed-metadata":
            module_file = (
                venv_state["root"]
                / "Lib"
                / "site-packages"
                / "noetrium"
                / "__init__.py"
            )
            return _receipt(
                name,
                0,
                {"version": "0.44.0", "module_file": str(module_file)},
            )
        if name == "research-program-load-1":
            return _receipt(name, 0, _identity())
        if name == "research-program-load-2":
            return _receipt(
                name,
                0,
                _identity(portfolio_digest="3" * 64),
            )
        rows = {
            "install-artifact": _receipt("install-artifact", 0),
            "project-create": _receipt("project-create", 0, {"ok": True}),
            "project-doctor": _receipt(
                "project-doctor",
                0,
                _doctor(ready=True),
            ),
            "project-test": _receipt("project-test", 0, {"ok": True}),
        }
        return rows[name]

    monkeypatch.setattr(npe, "_run", fake_run)
    result = npe.verify_npe_cleanroom(artifact)

    assert result.research_portfolio_loaded is True
    assert result.fresh_process_identity_stable is False
    assert result.npe_verified is False
    assert result.blocker_codes == ("RESEARCH_IDENTITY_DRIFT",)


def test_clean_room_rejects_installed_import_outside_verification_venv(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "noetrium.whl"
    artifact.write_bytes(b"wheel")
    _bind_fake_venv(monkeypatch)

    def fake_run(name, argv, cwd, env):
        del argv, cwd, env
        if name == "install-artifact":
            return _receipt(name, 0)
        if name == "installed-metadata":
            return _receipt(
                name,
                0,
                {
                    "version": "0.44.0",
                    "module_file": str(
                        tmp_path / "checkout" / "noetrium" / "__init__.py"
                    ),
                },
            )
        raise AssertionError(name)

    monkeypatch.setattr(npe, "_run", fake_run)
    result = npe.verify_npe_cleanroom(artifact)

    assert result.installed_import_isolated is False
    assert result.npe_verified is False
    assert result.blocker_codes == ("INSTALLED_IMPORT_ESCAPED_VENV",)

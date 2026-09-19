from __future__ import annotations

import hashlib
import json
from pathlib import Path

import scripts.verify_npe_cleanroom as npe


def _receipt(name: str, returncode: int, payload: dict | None = None, *, stdout: str | None = None) -> npe.CommandReceipt:
    text = stdout if stdout is not None else (json.dumps(payload) if payload is not None else "")
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
        json_output=text if npe._strict_json_object(text) is not None else None,
    )



def test_json_output_uses_complete_machine_receipt_not_human_tail() -> None:
    payload = {"ok": True, "padding": "x" * 6000, "result": {"value": 7}}
    text = json.dumps(payload)
    receipt = _receipt("large", 0, stdout=text)
    assert len(receipt.stdout_tail) == 4000
    assert npe._json_output(receipt) == payload


def test_json_output_rejects_duplicate_keys_and_non_finite_constants() -> None:
    duplicate = _receipt("duplicate", 0, stdout='{ "ok": true, "ok": false }')
    non_finite = _receipt("nonfinite", 0, stdout='{ "ok": true, "value": NaN }')
    assert npe._json_output(duplicate) is None
    assert npe._json_output(non_finite) is None

def _doctor(*, ready: bool, blocked: tuple[str, ...] = ()) -> dict:
    checks = [
        {"check_id": "public_import_boundary", "disposition": "pass", "summary": "public", "remediation": ""},
    ]
    for check_id in blocked:
        checks.append(
            {"check_id": check_id, "disposition": "blocked", "summary": "blocked", "remediation": "fix"}
        )
    return {
        "ok": ready,
        "command": "project doctor",
        "result": {
            "project_root": "project",
            "template_profile": "author",
            "template_revision": "noetrium.project-template.author.v2",
            "checks": checks,
        },
    }


def test_doctor_facts_preserve_public_boundary_and_blocker_ids() -> None:
    receipt = _receipt(
        "project-doctor",
        4,
        _doctor(ready=False, blocked=("participant_provider_readiness", "application_binding")),
    )
    ready, public_boundary, profile, template, blockers = npe._doctor_facts(receipt)
    assert ready is False
    assert public_boundary is True
    assert profile == "author"
    assert template == "noetrium.project-template.author.v2"
    assert blockers == ("participant_provider_readiness", "application_binding")


def test_doctor_facts_fail_closed_on_invalid_json() -> None:
    receipt = _receipt("project-doctor", 4, stdout="not-json")
    assert npe._doctor_facts(receipt) == (False, False, None, None, ("DOCTOR_RECEIPT_INVALID",))


def _bind_fake_venv(monkeypatch) -> dict[str, Path]:
    state: dict[str, Path] = {}

    def create(root: Path) -> bool:
        state["root"] = Path(root)
        return True

    monkeypatch.setattr(npe, "_create_venv", create)
    return state


def test_clean_room_reports_missing_venv_as_environment_blocker(tmp_path: Path, monkeypatch) -> None:
    artifact = tmp_path / "noetrium_platform.whl"
    artifact.write_bytes(b"wheel")
    monkeypatch.setattr(npe, "_create_venv", lambda root: False)
    monkeypatch.setattr(
        npe,
        "_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected command")),
    )

    result = npe.verify_npe_cleanroom(artifact)

    assert result.npe_verified is False
    assert result.blocker_codes == ("PYTHON_VENV_UNAVAILABLE",)
    assert result.commands == ()


def test_clean_room_records_level0_binding_blocker_without_false_pass(
    tmp_path: Path, monkeypatch
) -> None:
    artifact = tmp_path / "noetrium_platform.whl"
    artifact.write_bytes(b"wheel")
    venv_state = _bind_fake_venv(monkeypatch)
    rows = {
        "install-artifact": _receipt("install-artifact", 0),
        "project-create": _receipt("project-create", 0, {"ok": True, "result": {"template_profile": "author"}}),
        "project-doctor": _receipt(
            "project-doctor", 4,
            _doctor(ready=False, blocked=("level0_standard_bindings",)),
        ),
        "project-test": _receipt("project-test", 0, {"ok": True}),
    }
    def fake_run(name, argv, cwd, env):
        del argv, cwd, env
        if name == "installed-metadata":
            module_file = venv_state["root"] / "Lib" / "site-packages" / "noetrium_platform" / "api.py"
            return _receipt(name, 0, {"version": "0.43.1", "module_file": str(module_file)})
        return rows[name]
    monkeypatch.setattr(npe, "_run", fake_run)

    result = npe.verify_npe_cleanroom(artifact)
    assert result.template_profile == "author"
    assert result.npe_verified is False
    assert result.project_created is True
    assert result.generated_tests_passed is True
    assert result.public_import_boundary_passed is True
    assert "DOCTOR_BLOCKED:level0_standard_bindings" in result.blocker_codes
    assert "URE_LEVEL0_STANDARD_BINDINGS_UNAVAILABLE" in result.blocker_codes

def test_clean_room_verifies_explicit_downstream_lifecycle_and_fresh_reopen(
    tmp_path: Path, monkeypatch
) -> None:
    artifact = tmp_path / "noetrium_platform.whl"
    artifact.write_bytes(b"wheel")
    venv_state = _bind_fake_venv(monkeypatch)
    monkeypatch.setattr(npe, "_reference_project_package", lambda project: "npe_reference")
    monkeypatch.setattr(npe, "_materialize_reference_lifecycle", lambda *args: True)
    lifecycle = {
        "run": ("running", 3, False),
        "inspect": ("running", 3, False),
        "stop": ("stopped", 5, False),
        "resume": ("running", 7, False),
        "reconcile": ("running", 7, False),
        "evidence": ("running", 7, True),
    }
    rows = {
        "install-artifact": _receipt("install-artifact", 0),
        "project-create": _receipt("project-create", 0, {"ok": True}),
        "project-doctor": _receipt("project-doctor", 0, _doctor(ready=True)),
        "project-test": _receipt("project-test", 0, {"ok": True}),
    }
    def fake_run(name, argv, cwd, env):
        del argv, cwd, env
        if name == "installed-metadata":
            module_file = venv_state["root"] / "Lib" / "site-packages" / "noetrium_platform" / "api.py"
            return _receipt(name, 0, {"version": "0.43.1", "module_file": str(module_file)})
        if name.startswith("reference-lifecycle-"):
            action = name.removeprefix("reference-lifecycle-")
            lookup = "inspect" if action == "fresh-inspect" else action
            expected_state, generation, evidence = lifecycle[lookup]
            if action == "fresh-inspect":
                generation = 7
                evidence = True
            payload = {
                "control_revision": generation,
                "evidence_bundle": {} if evidence else None,
                "outcomes": {"evidence": "finalized_valid" if evidence else "not_observed"},
            }
            return _receipt(
                name,
                0,
                {"ok": True, "action": lookup, "state": expected_state, "payload": payload},
            )
        return rows[name]
    monkeypatch.setattr(npe, "_run", fake_run)
    result = npe.verify_npe_cleanroom(artifact)
    assert result.template_profile == "author"
    assert result.doctor_ready is True
    assert result.reference_lifecycle_complete is True, result.blocker_codes
    assert result.fresh_process_reopen_passed is True, result.blocker_codes
    assert result.npe_verified is True
    assert result.blocker_codes == ()


def test_clean_room_rejects_missing_reference_driver_after_author_readiness(
    tmp_path: Path, monkeypatch
) -> None:
    artifact = tmp_path / "noetrium_platform.whl"
    artifact.write_bytes(b"wheel")
    venv_state = _bind_fake_venv(monkeypatch)
    monkeypatch.setattr(npe, "_reference_project_package", lambda project: "npe_reference")
    monkeypatch.setattr(npe, "_materialize_reference_lifecycle", lambda *args: False)
    rows = {
        "install-artifact": _receipt("install-artifact", 0),
        "project-create": _receipt("project-create", 0, {"ok": True}),
        "project-doctor": _receipt("project-doctor", 0, _doctor(ready=True)),
        "project-test": _receipt("project-test", 0, {"ok": True}),
    }
    def fake_run(name, argv, cwd, env):
        del argv, cwd, env
        if name == "installed-metadata":
            module_file = venv_state["root"] / "Lib" / "site-packages" / "noetrium_platform" / "api.py"
            return _receipt(name, 0, {"version": "0.43.1", "module_file": str(module_file)})
        return rows[name]
    monkeypatch.setattr(npe, "_run", fake_run)
    result = npe.verify_npe_cleanroom(artifact)
    assert result.npe_verified is False
    assert result.blocker_codes == ("REFERENCE_DRIVER_TEMPLATE_MISSING",)

def test_clean_room_rejects_installed_import_outside_verification_venv(
    tmp_path: Path, monkeypatch
) -> None:
    artifact = tmp_path / "noetrium_platform.whl"
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
                {"version": "0.43.1", "module_file": str(tmp_path / "checkout" / "noetrium_platform" / "api.py")},
            )
        raise AssertionError(name)

    monkeypatch.setattr(npe, "_run", fake_run)
    result = npe.verify_npe_cleanroom(artifact)
    assert result.installed_import_isolated is False
    assert result.npe_verified is False
    assert result.blocker_codes == ("INSTALLED_IMPORT_ESCAPED_VENV",)

from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.kernel.unit import NoetriumUnit


def _direct_unit_state_root(
    project_roots: str | Path | tuple[str | Path, ...] | None,
    state_root: str | Path | None,
) -> Path:
    if state_root is not None:
        root = Path(state_root).expanduser().absolute()
    elif project_roots is None:
        root = Path(".").absolute() / ".noetrium" / "unit-execution"
    else:
        candidates = (
            tuple(Path(row).expanduser().absolute() for row in project_roots)
            if type(project_roots) is tuple
            else (Path(project_roots).expanduser().absolute(),)
        )
        if not candidates:
            raise ValueError("direct Unit project_roots cannot be empty")
        root = sorted(candidates, key=str)[0] / ".noetrium" / "unit-execution"
    if root.is_symlink():
        raise ValueError("direct Unit state root must not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _run_executable_unit(
    unit: NoetriumUnit,
    *,
    project_roots: str | Path | tuple[str | Path, ...] | None,
    state_root: str | Path | None,
    payload: object,
):
    from noetrium_platform.foundation.kernel.kernel import (
        DirectoryMachineJournal,
        canonical_digest,
        freeze_json,
    )
    from noetrium_platform.foundation.kernel.kernel.unit_host import (
        BoundExecutableUnit,
    )
    from noetrium_platform.foundation.kernel.kernel.universal import (
        executable_unit_domain,
        validate_executable_unit,
    )

    validate_executable_unit(unit)
    frozen_payload = freeze_json(payload)
    root = _direct_unit_state_root(project_roots, state_root)
    execution_identity = canonical_digest({
        "schema": "noetrium.direct-executable-unit.v1",
        "unit_digest": unit.unit_digest,
        "payload": frozen_payload,
    })
    host = BoundExecutableUnit(
        host_id=f"unit:{unit.unit_id}",
        unit=unit,
        journal=DirectoryMachineJournal(root / "unit-journal"),
        dependency_identity={
            "execution_mode": "direct",
            "unit_digest": unit.unit_digest,
            "domain": executable_unit_domain(unit),
        },
    )
    return host.execute(
        machine_id=f"unit:{execution_identity}",
        instance_identity={
            "schema": "noetrium.direct-executable-unit-instance.v1",
            "unit_digest": unit.unit_digest,
            "domain": executable_unit_domain(unit),
            "payload_digest": canonical_digest(frozen_payload),
        },
        binding=None,
        initial_data={},
        payload=frozen_payload,
        command_id_prefix=f"unit:{execution_identity}",
    )

def run(
    source: NoetriumUnit | str | Path | tuple[str | Path, ...] = ".",
    *,
    project_roots: str | Path | tuple[str | Path, ...] | None = None,
    state_root: str | Path | None = None,
    payload: object = None,
) -> object:
    """Execute one NoetriumUnit or load and execute one research root.

    Executable Units are a kernel primitive and require no research-domain
    wrapper. Research portfolios continue through the research composition
    path because they materialize model/environment/resource authorities.
    """
    if type(source) is NoetriumUnit and source.has_trait("unit.executable"):
        return _run_executable_unit(
            source,
            project_roots=project_roots,
            state_root=state_root,
            payload=payload,
        )

    from noetrium_platform.composition.operator.project.project_research_loader import (
        load_research_root,
    )

    resolved_state = None if state_root is None else Path(state_root)
    if type(source) is NoetriumUnit:
        roots_value = "." if project_roots is None else project_roots
        roots = (
            tuple(Path(row) for row in roots_value)
            if type(roots_value) is tuple
            else Path(roots_value)
        )
        loaded = load_research_root(
            source,
            project_roots=roots,
            state_root=resolved_state,
        )
    elif isinstance(source, (str, Path)) or type(source) is tuple:
        if project_roots is not None:
            raise ValueError("project_roots is only valid when source is NoetriumUnit")
        roots = (
            tuple(Path(row) for row in source)
            if type(source) is tuple
            else Path(source)
        )
        loaded = load_research_root(
            roots,
            state_root=resolved_state,
            revision_intent="working",
        )
    else:
        raise TypeError("run source must be NoetriumUnit, path, or path tuple")

    try:
        return loaded.run(payload=payload)
    finally:
        loaded.close()


__all__ = ("run",)

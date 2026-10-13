from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from noetrium_platform.composition.environment_profile_selection import (
    default_profiles_for_categories,
    required_environment_categories,
)
from noetrium_platform.composition.operator.project.project_execution_authority import (
    materialize_project_execution_authorities,
)
from noetrium_platform.composition.operator.project.project_research_loader import (
    LoadedProjectSource,
    load_project_source_snapshot,
    load_research_root,
)
from noetrium_platform.composition.research_portfolio_execution import (
    ResearchPortfolioExecutionResult,
    compose_research_portfolio_roots,
    open_local_research_execution_context,
    preflight_research_portfolio,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.portfolio.api import project_manifest_project_id
from noetrium_platform.product.research_control import ResearchExecutionTarget
from scripts.build_environment_images import (
    PYTHON_RUNTIME_CANONICAL_IMAGE,
    build_environment_images,
)

ENVIRONMENT_CATALOG = ROOT / "deploy" / "environments" / "catalog.json"


def _profile_enabled() -> bool:
    return os.environ.get("NOETRIUM_CONTROL_PROFILE", "").strip() == "1"


def _profile(stage: str, seconds: float) -> None:
    if _profile_enabled():
        print(
            json.dumps(
                {
                    "schema": "noetrium.control-profile.v1",
                    "stage": stage,
                    "seconds": round(seconds, 6),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )


def _root_set_id(project_roots: tuple[Path, ...]) -> str:
    resolved = tuple(sorted((str(path.expanduser().resolve()) for path in project_roots)))
    digest = canonical_digest(
        {
            "schema": "noetrium.project-root-set.v1",
            "roots": resolved,
        }
    )
    return f"research-root-{digest[:24]}"


def _source_state_root(state_root: Path, project_root: Path) -> Path:
    key = canonical_digest(
        {
            "schema": "noetrium.project-source-state.v1",
            "project_root": str(project_root.resolve()),
        }
    )
    return state_root / "project-sources" / key


def _load_sources(
    project_roots: tuple[Path, ...],
    *,
    state_root: Path,
) -> tuple[LoadedProjectSource, ...]:
    if not project_roots:
        raise ValueError("research root execution requires at least one --project")
    resolved = tuple(path.expanduser().resolve() for path in project_roots)
    if len(resolved) != len(set(resolved)):
        raise ValueError("research root execution project roots must be unique")
    rows: list[LoadedProjectSource] = []
    try:
        for root in resolved:
            rows.append(
                load_project_source_snapshot(
                    root,
                    state_root=_source_state_root(state_root, root),
                )
            )
        project_ids = tuple(project_manifest_project_id(row.manifest) for row in rows)
        if len(project_ids) != len(set(project_ids)):
            raise ValueError("research root execution project identities must be unique")
        return tuple(rows)
    except BaseException:
        for row in reversed(rows):
            row.close()
        raise


def _ensure_environment_closure(portfolio, *, work_root: Path) -> tuple[str, ...]:
    categories = required_environment_categories(portfolio)
    if not categories:
        return ()
    catalog = json.loads(ENVIRONMENT_CATALOG.read_text(encoding="utf-8"))
    if type(catalog) is not dict:
        raise ValueError("environment profile catalog must be a JSON object")
    profiles = default_profiles_for_categories(catalog, categories)
    build_environment_images(
        profiles=profiles,
        work_root=work_root.resolve(),
        output=work_root.resolve() / "environment-image-build.json",
        python_runtime_image=os.environ.get(
            "PYTHON_RUNTIME_IMAGE", PYTHON_RUNTIME_CANONICAL_IMAGE
        ),
        python_runtime_canonical_image=os.environ.get(
            "PYTHON_RUNTIME_CANONICAL_IMAGE", PYTHON_RUNTIME_CANONICAL_IMAGE
        ),
        profile_build_input_overrides={},
    )
    return profiles


def _emit(result, *, mode: str, project_roots: tuple[Path, ...]) -> None:
    payload = {
        "schema": "noetrium.research-root-execution.v1",
        "mode": mode,
        "project_roots": tuple(str(path.resolve()) for path in project_roots),
        "project_count": len(project_roots),
        "portfolio_id": result.portfolio_id,
        "portfolio_digest": result.portfolio_digest,
        "authority_manifest_digest": result.authority_manifest_digest,
        "execution_id": result.execution_id,
        "result_digest": result.result_digest,
    }
    if mode == "preflight":
        payload.update(
            {
                "revision_digest": result.revision_digest,
                "selected_node_ids": result.selected_node_ids,
                "admission_digests": result.admission_digests,
                "preflight_digest": result.preflight_digest,
            }
        )
    else:
        payload.update(
            {
                "revision_digest": result.revision.revision_digest,
                "state": result.receipt.state,
                "control_revision_digest": result.receipt.control_revision_digest,
            }
        )
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def run(
    project_roots: tuple[Path, ...],
    *,
    state_root: Path,
    work_root: Path,
    mode: str,
) -> object:
    if mode not in {"preflight", "execute"}:
        raise ValueError("research root execution mode must be preflight or execute")
    resolved_state = state_root.expanduser().resolve()
    resolved_state.mkdir(parents=True, exist_ok=True)

    if mode == "execute":
        total_started = perf_counter()
        stage_started = total_started
        loaded = load_research_root(
            project_roots,
            state_root=resolved_state / "research",
            revision_intent="working",
        )
        _profile("load_research_root", perf_counter() - stage_started)
        try:
            stage_started = perf_counter()
            _ensure_environment_closure(loaded.portfolio, work_root=work_root)
            _profile("environment_closure", perf_counter() - stage_started)
            if _profile_enabled():
                stage_started = perf_counter()
                loaded.ensure_execution_plane()
                _profile("execution_plane", perf_counter() - stage_started)
            stage_started = perf_counter()
            receipt = loaded.run()
            _profile("research_root_run", perf_counter() - stage_started)
            authority_manifest_digest = loaded.authority_manifest_digest
            if authority_manifest_digest is None:
                raise RuntimeError(
                    "Research execution RUN completed without execution-authority identity"
                )
            result = ResearchPortfolioExecutionResult(
                loaded.portfolio.unit_id,
                loaded.portfolio.unit_digest,
                authority_manifest_digest,
                loaded.default_execution_id,
                loaded.revision,
                receipt,
            )
        finally:
            stage_started = perf_counter()
            loaded.close()
            _profile("close", perf_counter() - stage_started)
        _profile("execute_total", perf_counter() - total_started)
        return result

    sources = _load_sources(project_roots, state_root=resolved_state)
    try:
        portfolio = (
            sources[0].portfolio
            if len(sources) == 1
            else compose_research_portfolio_roots(
                tuple(row.portfolio for row in sources),
                root_id=_root_set_id(project_roots),
            )
        )
        manifests = tuple(row.manifest for row in sources)
        _ensure_environment_closure(portfolio, work_root=work_root)
        with open_local_research_execution_context(
            resolved_state / "execution",
        ) as context:
            authorities = materialize_project_execution_authorities(
                context,
                portfolio,
                manifests,
            )
            try:
                return preflight_research_portfolio(
                    portfolio,
                    state_root=resolved_state / "research-preflight",
                    authorities=authorities,
                    execution_id=portfolio.unit_id,
                    execution_pool=context.execution_pool,
                    operation_dispatcher=context.runtime.operation_runtime.dispatcher,
                    content_authorities=context.content,
                )
            finally:
                authorities.retire()
    finally:
        for row in reversed(sources):
            row.close()


def _result_exit_code(result: object, *, mode: str) -> int:
    """Map the canonical research receipt to process success/failure."""

    if mode == "preflight":
        return 0
    if mode != "execute":
        raise ValueError("research root execution mode must be preflight or execute")
    if not isinstance(result, ResearchPortfolioExecutionResult):
        raise TypeError(
            "execute result must be ResearchPortfolioExecutionResult"
        )
    return 0 if result.receipt.state == "succeeded" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Execute one recursive NoetriumUnit root loaded from one or more "
            "downstream project sources."
        )
    )
    projects = parser.add_mutually_exclusive_group(required=True)
    projects.add_argument("--project", action="append", type=Path)
    projects.add_argument("--project-roots-file", type=Path)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--preflight", action="store_true")
    modes.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    mode = "preflight" if args.preflight else "execute"
    if args.project_roots_file is not None:
        raw = args.project_roots_file.read_text(encoding="utf-8").splitlines()
        project_roots = tuple(Path(row) for row in raw if row.strip())
        if not project_roots:
            raise ValueError("project roots file must contain at least one path")
    else:
        project_roots = tuple(args.project or ())
    result = run(
        project_roots,
        state_root=args.state_root,
        work_root=args.work_root,
        mode=mode,
    )
    _emit(result, mode=mode, project_roots=project_roots)
    return _result_exit_code(result, mode=mode)


if __name__ == "__main__":
    raise SystemExit(main())

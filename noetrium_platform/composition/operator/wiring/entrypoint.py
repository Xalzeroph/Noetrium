"""The sole public operator entry; legacy research wiring is an internal backend."""

from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
import os
from pathlib import Path
import sys

from noetrium_platform.product.operator.runtime.unified_parser import (
    build_parser,
    print_help_path,
    PAPER_GUIDE,
)
from noetrium_platform.composition.operator.cli_context import (
    Workspace,
    initialize_workspace,
    locate_workspace,
    real_directory,
    require_workspace,
    validate_name,
)
from noetrium_platform.composition.operator.cli_context import (
    attach,
    execution_environment,
    existing_record,
    freeze_new_run,
    graph_summary,
    owner_alive,
    owner_identity,
    version_summary,
    recovery_runtime_binding,
    execution_record,
    read_log_tail,
)

_PLATFORM_ROOT = Path(__file__).resolve().parents[4]
_DEV_MODULES = {
    "architecture": "noetrium_platform.foundation.governance.architecture.gate",
    "algorithm": "noetrium_platform.foundation.governance.analysis.algorithm.cli",
    "concurrency": "noetrium_platform.foundation.governance.analysis.concurrency.cli",
    "performance": "noetrium_platform.foundation.governance.analysis.performance.cli",
    "boundary": "noetrium_platform.foundation.governance.architecture.repository_boundary.cli",
    "release": "noetrium_platform.foundation.governance.release.cli",
}


@contextmanager
def _command_runner():
    # No providers, timers or process authorities exist on parse/help/config paths.
    from noetrium_platform.composition.concurrency import (
        build_execution_concurrency_runtime,
        build_scheduling_authority,
    )
    from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import (
        build_local_command_runner,
    )

    runtime = build_execution_concurrency_runtime(
        scheduling_authority=build_scheduling_authority()
    )
    try:
        yield build_local_command_runner(
            runtime.open_task_group("operator-entrypoint"),
            default_timeout_seconds=2592000,
        )
    finally:
        runtime.close()


def _emit(result):
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def _show_record(row):
    print("Run: " + row["name"])
    print(
        "Owner process: "
        + (
            "alive"
            if owner_alive(row)
            else "not alive; consult durable state before recovery"
        )
    )
    print("Frozen platform: " + row["platform_root"])
    binding = recovery_runtime_binding(row)
    if binding:
        print(
            "Execution runtime: "
            + binding["platform_root"]
            + " @ "
            + binding["revision"]
        )
    print("Paper roots: " + ", ".join(row["project_roots"]))
    print("State: " + row["data_root"])
    states = graph_summary(row)
    print(
        "Recorded node states: "
        + (json.dumps(states, sort_keys=True) if states else "not materialized")
    )
    return 0


def _workspace(args):
    if args.action == "init":
        ws = initialize_workspace(
            args.workspace,
            platform_root=args.platform_root or _PLATFORM_ROOT,
            data_root=args.data_root,
            projects=args.project or (),
            env_file=args.env_file,
        )
        print("Workspace: " + str(ws.path))
        print("Default paper set: " + ", ".join(ws.data["default_projects"]))
        print("Next: noetrium run | noetrium research status | noetrium help research")
        return 0
    ws = require_workspace(args.workspace)
    if args.action == "attach":
        row = attach(
            ws,
            args.name,
            args.platform_root,
            args.data_root,
            args.project,
            args.env_file,
        )
        print("Bound existing run without starting it: " + row["name"])
        return 0
    if args.action == "doctor":
        _, roots = ws.roots()
        platform = real_directory(ws.resolve(ws.data["platform_root"]))
        if not (platform / "deploy/noetrium").is_file():
            raise ValueError("platform root has no deploy/noetrium")
        for root in roots:
            if not (root / "project.manifest.json").is_file():
                raise ValueError("paper has no project.manifest.json: " + str(root))
        if ws.data.get("env_file") and not ws.resolve(ws.data["env_file"]).is_file():
            raise ValueError("configured environment file is missing")
        print("Workspace paths and manifest files exist. No services started.")
        return 0
    # Environment values and credentials are never read or displayed here.
    print(json.dumps(ws.data, indent=2, ensure_ascii=False))
    return 0


def _registry(args):
    ws = require_workspace(args.workspace)
    if args.action == "list":
        for name, value in ws.data["projects"].items():
            suffix = " [default]" if name in ws.data["default_projects"] else ""
            print(name + suffix + ": " + str(ws.resolve(value)))
        return 0

    def change(data):
        if args.action == "add":
            name = validate_name(args.name)
            if name in data["projects"]:
                raise ValueError("project name already registered: " + name)
            root = real_directory(args.path)
            if not (root / "project.manifest.json").is_file():
                raise ValueError("project requires project.manifest.json")
            data["projects"][name] = str(root)
        elif args.action == "use":
            if len(set(args.names)) != len(args.names):
                raise ValueError("default paper set contains duplicate names")
            if any(name not in data["projects"] for name in args.names):
                raise ValueError(
                    "every default paper must first be registered with project add"
                )
            candidate = Workspace(ws.path, data)
            candidate.roots(args.names)
            data["default_projects"] = list(args.names)
        else:
            if args.name not in data["projects"]:
                raise ValueError("unknown project: " + args.name)
            del data["projects"][args.name]
            data["default_projects"] = [
                n for n in data["default_projects"] if n != args.name
            ]

    updated = ws.update(change)
    print("Default paper set: " + ", ".join(updated.data["default_projects"]))
    return 0


def _workspace_optional(args):
    path = locate_workspace(getattr(args, "workspace", None))
    return Workspace.load(path) if path is not None else None


def _direct_context(args, ws):
    platform = real_directory(
        os.environ.get("NOETRIUM_PLATFORM_ROOT")
        or (ws.resolve(ws.data["platform_root"]) if ws else _PLATFORM_ROOT)
    )
    needs_projects = args.group in ("research", "project") and not (
        args.group == "project" and args.action == "create"
    )
    if not needs_projects:
        roots = ()
    elif ws:
        _, roots = ws.roots(getattr(args, "project", None))
    else:
        roots = tuple(real_directory(p) for p in (getattr(args, "project", None) or ()))
    data = (
        getattr(args, "data_root", None)
        or os.environ.get("NOETRIUM_DATA_ROOT")
        or str(platform / ".noetrium")
    )
    env = (
        getattr(args, "env_file", None)
        or (ws.data.get("env_file") if ws else None)
        or os.environ.get("NOETRIUM_CONTROL_ENV_FILE")
    )
    return {
        "platform_root": str(platform),
        "project_roots": [str(p) for p in roots],
        "data_root": str(Path(data).absolute()),
        "env_file": str(ws.resolve(env) if ws and env else Path(env).absolute())
        if env
        else None,
    }


def _backend(row, command, arguments, runner, *, launch=False):
    row = execution_record(row)
    backend = Path(row["platform_root"]) / "deploy/noetrium-backend.sh"
    if not backend.is_file():
        # Existing frozen executions retain their exact pre-unification backend.
        backend = Path(row["platform_root"]) / "deploy/noetrium"
    if not backend.is_file():
        raise ValueError(
            "Deployment backend is missing; configure workspace init --platform-root with a Noetrium checkout"
        )
    argv = [str(backend), *command]
    for root in (
        row["project_roots"]
        if command[0]
        not in (
            "doctor",
            "build",
            "plan",
            "requirements",
            "audit-finalization",
            "env",
            "docker",
        )
        and command != ["project", "create"]
        else ()
    ):
        argv += ["--project", root]
    argv.extend(arguments[1:] if arguments[:1] == ["--"] else arguments)
    env = execution_environment(row)
    if launch:
        log = Path(row.get("launch_log") or str(Path(row["data_root"]) / "launch.log"))
        log.parent.mkdir(parents=True, exist_ok=True)
        env["NOETRIUM_LAUNCH_LOG"] = str(log)
        print(
            "Executing " + command[0] + " for " + row["name"] + "; log: " + str(log),
            flush=True,
        )
        # Process supervision remains the owner. Keep long-running child output
        # on disk instead of accumulating it in the process capture buffer.
        argv = [
            "sh",
            "-c",
            'exec "$@" >>"$NOETRIUM_LAUNCH_LOG" 2>&1',
            "noetrium-launch",
            *argv,
        ]
    return _emit(
        runner.run(tuple(argv), cwd=Path(row["platform_root"]), environment=env)
    )


def _research(args):
    ws = require_workspace(args.workspace)
    if args.run_name and not args.project:
        names, roots = (), ()
    else:
        names, roots = ws.roots(args.project)
    row = (
        ws.active_record(names, args.run_name)
        if args.action in ("status", "logs")
        else existing_record(ws, names, args.run_name)
    )
    action = args.action
    arguments = getattr(args, "arguments", [])
    if row and (args.data_root or args.env_file) and not (action == "run" and args.new):
        raise ValueError(
            "recorded runs retain their original state/environment; use workspace attach to bind an explicit existing run"
        )
    if action == "run":
        if row is not None and not args.new and (args.committed or args.revision):
            raise ValueError(
                "source selection creates a new experiment; add --new, or capture a version without starting it"
            )
        if args.name and not args.new and row is not None:
            raise ValueError(
                "--name names a new run; add --new to create a separate experiment"
            )
        if args.run_name and args.new:
            raise ValueError(
                "--run selects an existing run; --new creates one. Use --name to name a new run"
            )
        # One process lock per canonical paper set closes the selection/start
        # race across concurrent invocations. Never hold a config lock on child IO.
        if row is not None and not args.new:
            _show_record(row)
            print(
                "Existing run selected. Use research resume for recovery, or run --new for a separate experiment."
            )
            return 0
        with ws.launch_guard(names):
            ws = Workspace.load(ws.path)
            row = existing_record(ws, names, args.run_name)
            if row is not None and not args.new:
                _show_record(row)
                print(
                    "Existing run selected. Use research resume for recovery, or run --new for a separate experiment."
                )
                return 0
            if args.run_name and row is None:
                raise ValueError("selected run does not exist")
            if args.data_root:
                raise ValueError(
                    "new run state is allocated from workspace data_root; configure it with workspace init"
                )
            with _command_runner() as runner:
                row = freeze_new_run(
                    ws,
                    names,
                    roots,
                    runner,
                    name=args.name,
                    env_file=args.env_file,
                    committed=args.committed,
                    revisions=args.revision,
                )
        return _execute_record(ws, row, "run", arguments, require_prepared=True)
    if action == "preflight" and row is None:
        with _command_runner() as runner:
            return _backend(_direct_context(args, ws), ["preflight"], arguments, runner)
    if row is None:
        raise ValueError(
            "no recorded run for this paper set; use noetrium run, or workspace attach for an existing execution"
        )
    if action == "status":
        return _show_record(row)
    if action == "logs":
        if args.lines <= 0:
            raise ValueError("--lines must be positive")
        log = Path(row.get("launch_log") or str(Path(row["data_root"]) / "launch.log"))
        if not log.is_file():
            print("Launcher log is not available: " + str(log))
            return 0
        for line in read_log_tail(log, args.lines):
            print(line, end="")
        return 0
    if action in ("resume", "retry"):
        return _execute_record(ws, row, action, arguments)
    with _command_runner() as runner:
        return _backend(row, [action], arguments, runner)


def _execute_record(
    ws, row, action, arguments, *, require_prepared=False, prepare=None
):
    with ws.execution_guard(row["name"]):
        current = existing_record(ws, (), row["name"])
        if owner_alive(current):
            raise ValueError(
                "run already has a live owner; inspect, pause or drain it before starting another execution driver"
            )
        if require_prepared and current.get("launch_phase") != "prepared":
            raise ValueError(
                "run has already been launched; use resume/retry for recovery, or runs rerun for fresh state"
            )
        # Validate the actual execution code before making recovery transitions.
        execution_record(current)
        session = prepare(current) if prepare is not None else None
        ws.update_record(
            row["name"],
            {
                "owner": owner_identity(),
                "last_action": action,
                "launch_phase": "running",
            },
        )
        code = None
        try:
            if session is not None:
                session.mark("executing")
            # The execution lock and owner outlive process-supervisor teardown.
            # Recovery drivers have the same unbounded log stream as fresh runs.
            with _command_runner() as runner:
                outcome = _backend(current, [action], arguments, runner, launch=True)
            code = outcome
            return code
        finally:
            if session is not None:
                try:
                    session.mark(
                        "finished" if code is not None else "interrupted",
                        exit_code=code,
                    )
                finally:
                    ws.update_record(
                        row["name"],
                        {
                            "owner": None if code is not None else owner_identity(),
                            "last_exit": code,
                            "launch_phase": "exited"
                            if code is not None
                            else "interrupted",
                        },
                    )
            else:
                ws.update_record(
                    row["name"],
                    {
                        "owner": None if code is not None else owner_identity(),
                        "last_exit": code,
                        "launch_phase": "exited" if code is not None else "interrupted",
                    },
                )


def _recover(args):
    from noetrium_platform.composition.operator.recovery import (
        recovery_plan,
        prepare_recovery,
    )

    ws = require_workspace(args.workspace)
    names = () if args.run_name and not args.project else ws.roots(args.project)[0]
    row = ws.active_record(names, args.run_name)
    if row is None:
        raise ValueError("no recorded run; create or attach an execution first")
    if args.data_root or args.env_file:
        raise ValueError("recovery retains the original state and environment")
    if args.plan:
        print(json.dumps(recovery_plan(row), indent=2, ensure_ascii=False))
        return 0
    return _execute_record(
        ws,
        row,
        "resume",
        [],
        prepare=lambda current: prepare_recovery(
            current,
            retry_failed=args.retry_failed,
            retry_uncertain=args.retry_uncertain,
            reason=args.reason,
        ),
    )


def _history(args):
    verb = args.history_action
    if not verb:
        print_help_path(build_parser(), ["research", args.action])
        return 0
    ws = require_workspace(args.workspace)
    if args.action == "checkpoints":
        row = ws.active_record((), args.run_name)
        from noetrium_platform.composition.research_checkpoint_store import (
            DirectoryResearchGraphCheckpointStore,
        )

        checkpoints = []
        root = Path(row["data_root"]) / "projects/root-sets"
        if verb == "show" and (
            len(args.digest) != 64
            or any(c not in "0123456789abcdef" for c in args.digest)
        ):
            raise ValueError(
                "checkpoint digest must contain 64 lowercase hexadecimal characters"
            )
        pattern = (
            "*/research/graph-checkpoints/objects/"
            + (args.digest if verb == "show" else "*")
            + ".json"
        )
        for path in root.glob(pattern):
            checkpoints.append(
                DirectoryResearchGraphCheckpointStore.read_document(path)
            )
        if verb == "show":
            checkpoints = [
                p for p in checkpoints if p["checkpoint_digest"] == args.digest
            ]
            if not checkpoints:
                raise ValueError("checkpoint digest is not recorded in this run")
        else:
            checkpoints = [
                {
                    key: p[key]
                    for key in (
                        "checkpoint_digest",
                        "execution_cut_id",
                        "research_revision_digest",
                        "snapshot_generation",
                        "control_phase",
                        "selected_node_ids",
                    )
                }
                for p in checkpoints
            ]
        print(
            json.dumps(
                checkpoints,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
        )
        return 0
    if verb == "list":
        rows = ws.records()
        if args.action == "versions":
            payload = [version_summary(row) for row in rows]
        else:
            payload = [
                {
                    "name": r["name"],
                    "owner_alive": owner_alive(r),
                    "launch_phase": r.get("launch_phase", "imported"),
                    "labels": ws.data.get("run_labels", {}).get(r["name"], []),
                    "parent_run": r.get("parent_run"),
                    "created_at": r.get("created_at"),
                }
                for r in rows
            ]
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            for row in payload:
                print(json.dumps(row, ensure_ascii=False))
        return 0
    if verb == "compare":
        left, right = (
            ws.active_record((), getattr(args, key)) for key in ("left", "right")
        )
        payload = {
            "left": version_summary(left),
            "right": version_summary(right),
            "same_paper_origins": sorted(left["selected_roots"])
            == sorted(right["selected_roots"]),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    if verb == "capture":
        names, roots = ws.roots(args.project)
        with _command_runner() as runner:
            row = freeze_new_run(
                ws,
                names,
                roots,
                runner,
                name=args.name,
                env_file=args.env_file,
                committed=args.committed,
                revisions=args.revision,
                activate=False,
            )
        print(
            json.dumps(version_summary(row), indent=2)
            if args.json
            else "Version prepared: "
            + row["name"]
            + "; next: noetrium research runs start "
            + row["name"]
        )
        return 0
    row = ws.active_record((), args.name)
    if verb == "show":
        payload = version_summary(row) if args.action == "versions" else row
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    if verb == "label":
        if args.clear and args.labels:
            raise ValueError("--clear cannot be combined with new labels")
        for label in args.labels:
            if not label.strip() or not label.isprintable():
                raise ValueError("labels must be nonempty printable text")
        if args.clear or args.labels:

            def change(data):
                store = data.setdefault("run_labels", {})
                store[row["name"]] = (
                    []
                    if args.clear
                    else list(
                        dict.fromkeys([*store.get(row["name"], []), *args.labels])
                    )
                )

            ws = ws.update(change)
        print(
            json.dumps(
                ws.data.get("run_labels", {}).get(row["name"], []), ensure_ascii=False
            )
        )
        return 0
    if verb == "select":
        registered = {
            str(ws.resolve(value).resolve()): name
            for name, value in ws.data["projects"].items()
        }
        if any(path not in registered for path in row["selected_roots"]):
            raise ValueError(
                "register the original paper directories before selecting this set; historical commands can use --run NAME without changing defaults"
            )
        names = [registered[path] for path in row["selected_roots"]]

        def change(data):
            data["default_projects"] = names
            data.setdefault("active_runs", {})[ws.roots_key(row["selected_roots"])] = (
                row["name"]
            )

        ws.update(change)
        print("Default run selected: " + row["name"])
        return 0
    if verb == "start":
        return _execute_record(ws, row, "run", [], require_prepared=True)
    if verb == "rerun":
        with _command_runner() as runner:
            fresh = freeze_new_run(
                ws, (), (), runner, name=args.new_name, source_record=row
            )
        return _execute_record(ws, fresh, "run", [], require_prepared=True)
    raise ValueError("unsupported history action")


def _guide(args):
    stage = args.stage
    ws = _workspace_optional(args)
    if stage == "next":
        if ws is None:
            stage = "setup"
        elif not ws.data["default_projects"]:
            stage = "design"
        else:
            names, _roots = ws.roots()
            row = ws.active_record(names)
            if row is None:
                stage = "pilot"
            else:
                states = graph_summary(row)
                print(
                    "Selected run: "
                    + row["name"]
                    + "; recorded states: "
                    + json.dumps(states, sort_keys=True)
                )
                if (
                    states.get("failed")
                    or states.get("reconcile_required")
                    or (not owner_alive(row) and states.get("running"))
                ):
                    stage = "recover"
                elif owner_alive(row):
                    stage = "observe"
                elif row.get("launch_phase") == "prepared":
                    stage = "pilot"
                else:
                    stage = "analyze"
    selected = PAPER_GUIDE.items() if stage == "all" else ((stage, PAPER_GUIDE[stage]),)
    for name, (description, commands) in selected:
        print(name + ": " + description)
        for command in commands:
            print("  noetrium " + command)
    return 0


def main(argv=None):
    tokens = list(sys.argv[1:] if argv is None else argv)
    if tokens[:2] == ["dev", "release"]:
        from noetrium_platform.foundation.governance.release.cli import main as release_main

        return release_main(tokens[2:])
    if tokens[:3] == ["help", "dev", "release"]:
        from noetrium_platform.foundation.governance.release.cli import main as release_main

        return release_main(["--help", *tokens[3:]])
    if tokens[:2] == ["infra", "manage"] or tokens[:3] == ["help", "infra", "manage"]:
        # Management parses before constructing its provider plane. Its full
        # nested parser is loaded only for this group.
        from noetrium_platform.composition.operator.maintenance.management_cli import (
            _build_parser,
            main as manage_main,
        )

        management_parser = _build_parser()
        management_parser.prog = "noetrium infra manage"
        if tokens[:3] == ["help", "infra", "manage"]:
            print_help_path(management_parser, tokens[3:])
            return 0
        if len(tokens) == 2:
            management_parser.print_help()
            return 0
        return manage_main(tokens[2:])
    parser = build_parser()
    if not tokens:
        parser.print_help()
        return 0
    try:
        args, unknown = parser.parse_known_args(tokens)
        if args.group == "help":
            print_help_path(parser, args.path)
            return 0
        if args.group == "run":
            args.group, args.action = "research", "run"
            args.arguments = []
        if unknown:
            if args.group in (
                "workspace",
                "research",
                "run",
                "diagnose",
            ) or not hasattr(args, "arguments"):
                parser.error("unrecognized arguments: " + " ".join(unknown))
            args.arguments = unknown + args.arguments
        if args.group in (
            "workspace",
            "project",
            "research",
            "infra",
            "dev",
        ) and not getattr(args, "action", None):
            print_help_path(parser, [args.group])
            return 0
        if args.group == "guide":
            return _guide(args)
        if args.group == "research" and args.action in (
            "runs",
            "versions",
            "checkpoints",
        ):
            return _history(args)
        if args.group == "workspace":
            return _workspace(args)
        if args.group == "project" and args.action in ("list", "use", "add", "remove"):
            return _registry(args)
        if args.group == "research":
            if args.action == "recover":
                return _recover(args)
            return _research(args)
        if args.group == "dev":
            if not args.dev_command:
                print_help_path(parser, ["dev", args.action])
                return 0
            module = importlib.import_module(_DEV_MODULES[args.action])
            if args.action == "architecture":
                return module.main()
            forwarded = tokens[3:] if args.action == "boundary" else tokens[2:]
            return module.main(forwarded)
        if args.group == "diagnose":
            if not getattr(args, "diagnostic_command", None):
                print_help_path(
                    parser,
                    ["diagnose"]
                    + ([args.diagnostic_group] if args.diagnostic_group else []),
                )
                return 0
            from noetrium_platform.product.operator.runtime.cli import run_operator_cli
            from .runtime import build_operator_handler

            return run_operator_cli(
                build_operator_handler(), [args.diagnostic_command, *tokens[3:]]
            )
        if (
            args.group == "infra"
            and args.action in ("env", "docker")
            and not args.infra_command
        ):
            print_help_path(parser, ["infra", args.action])
            return 0
        ws = _workspace_optional(args)
        with _command_runner() as runner:
            command = (
                ["project", args.action] if args.group == "project" else [args.action]
            )
            arguments = args.arguments
            if getattr(args, "infra_command", None):
                command.append(args.infra_command)
            return _backend(_direct_context(args, ws), command, arguments, runner)
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        print("noetrium: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""One human-facing command tree. Parsing/help never constructs a runtime."""

from __future__ import annotations
import argparse

RESEARCH_ACTIONS = (
    "run",
    "status",
    "inspect",
    "logs",
    "preflight",
    "pause",
    "drain",
    "interrupt",
    "resume",
    "retry",
    "cancel",
    "checkpoint",
    "reconcile",
    "migrate",
    "retire",
)


def _target(parser, *, projects=True, runs=True):
    parser.add_argument(
        "--workspace",
        help="workspace file; otherwise discovered in the current directory and its parents",
    )
    if projects:
        parser.add_argument(
            "--project",
            action="append",
            help="registered project name or directory; repeat to compose multiple papers",
        )
    if runs:
        parser.add_argument(
            "--run",
            dest="run_name",
            help="recorded run name; defaults to this project set’s active run",
        )
    parser.add_argument(
        "--data-root", help="explicit data-root override for an unrecorded execution"
    )
    parser.add_argument("--env-file", help="explicit environment configuration file")


def build_parser():
    p = argparse.ArgumentParser(
        prog="noetrium",
        description="One entry for research, multi-paper execution, infrastructure and diagnostics.",
        epilog="First time: noetrium workspace init --project /path/to/paper\nThen: noetrium run | noetrium research status\nExplore: noetrium help research",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    groups = p.add_subparsers(dest="group")
    help_parser = groups.add_parser(
        "help", help="explore a command group without starting services"
    )
    help_parser.add_argument("path", nargs="*")
    run = groups.add_parser(
        "run", help="shortcut for research run with your saved project set"
    )
    _target(run)
    run.add_argument(
        "--new",
        action="store_true",
        help="freeze committed sources and start a separate run",
    )
    run.add_argument("--name", help="optional name for the new run")
    run.add_argument(
        "--committed",
        action="store_true",
        help="explicitly freeze committed HEAD; working edits are excluded",
    )
    run.add_argument(
        "--revision",
        action="append",
        default=[],
        help="platform=REF or PAPER=REF; immutable selected source commit",
    )
    research = groups.add_parser(
        "research", help="run and control one paper or a composed paper set"
    )
    actions = research.add_subparsers(dest="action")
    descriptions = {
        "run": "start or identify the active execution",
        "status": "inspect the active execution",
        "logs": "read the selected run’s launcher log",
        "preflight": "validate environment and research closure without executing",
        "resume": "resume the original frozen execution",
        "migrate": "explicitly migrate a research revision",
    }
    for name in RESEARCH_ACTIONS:
        a = actions.add_parser(
            name, help=descriptions.get(name, name + " research execution")
        )
        _target(a)
        if name == "run":
            a.description = "Automatically builds required environments, compiles and validates Research, then executes frozen sources. Existing runs are selected without restarting."
            a.add_argument("--new", action="store_true")
            a.add_argument("--name")
            a.add_argument("--committed", action="store_true")
            a.add_argument("--revision", action="append", default=[])
        if name == "logs":
            a.add_argument("--lines", type=int, default=50)
        if name == "retry":
            a.description = "Retry definitively failed nodes. For uncertain effects or lost acknowledgements, use reconcile instead of blind retry."
        if name == "reconcile":
            a.description = "Resolve uncertain execution state and lost acknowledgements from durable evidence before blindly retrying."
        a.add_argument(
            "arguments",
            nargs=argparse.REMAINDER,
            help="advanced research-control arguments; separate with --",
        )
    recovery = actions.add_parser(
        "recover",
        help="recover recorded progress with backups and explicit retry policy",
    )
    _target(recovery)
    recovery.add_argument(
        "--plan",
        action="store_true",
        help="read the recovery plan without changing state",
    )
    recovery.add_argument(
        "--retry-failed",
        action="store_true",
        help="requeue definitively failed nodes and their blocked descendants",
    )
    recovery.add_argument(
        "--retry-uncertain",
        action="store_true",
        help="explicitly allow replay of uncertain external effects",
    )
    recovery.add_argument("--reason", help="required audit reason for uncertain replay")
    for group_name, verbs in (
        ("runs", ("list", "show", "select", "label", "compare", "start", "rerun")),
        ("versions", ("list", "show", "compare", "capture")),
        ("checkpoints", ("list", "show")),
    ):
        group = actions.add_parser(
            group_name, help=group_name + " history and provenance"
        )
        children = group.add_subparsers(dest="history_action")
        for verb in verbs:
            child = children.add_parser(verb, help=verb + " " + group_name)
            child.add_argument("--workspace")
            if group_name == "checkpoints":
                child.add_argument("--run", dest="run_name", required=True)
                if verb == "show":
                    child.add_argument("digest")
            elif verb in ("show", "select", "label", "start", "rerun"):
                child.add_argument("name")
                if verb == "label":
                    child.add_argument("labels", nargs="*")
                    child.add_argument("--clear", action="store_true")
                if verb == "rerun":
                    child.add_argument("--name", dest="new_name", required=True)
            elif verb == "compare":
                child.add_argument("left")
                child.add_argument("right")
            elif verb == "capture":
                child.add_argument("--name", required=True)
                child.add_argument("--project", action="append")
                child.add_argument("--env-file")
                child.add_argument("--committed", action="store_true")
                child.add_argument("--revision", action="append", default=[])
            if group_name != "checkpoints":
                child.add_argument("--json", action="store_true")
    guide = groups.add_parser(
        "guide",
        help="paper lifecycle guidance; reads evidence without starting services",
    )
    guide.add_argument(
        "stage",
        nargs="?",
        default="next",
        choices=(
            "next",
            "all",
            "setup",
            "design",
            "pilot",
            "formal",
            "observe",
            "recover",
            "analyze",
            "write",
            "submit",
            "revise",
            "archive",
        ),
    )
    guide.add_argument("--workspace")
    workspace = groups.add_parser(
        "workspace", help="first-time setup and inspect saved execution defaults"
    )
    ws = workspace.add_subparsers(dest="action")
    init = ws.add_parser(
        "init", help="create defaults once; never starts an experiment"
    )
    init.add_argument("--workspace")
    init.add_argument("--platform-root")
    init.add_argument("--data-root", default=".noetrium")
    init.add_argument(
        "--project",
        action="append",
        help="PATH or NAME=PATH; repeat to save a multi-paper default set",
    )
    init.add_argument("--env-file")
    for name in ("show", "doctor"):
        a = ws.add_parser(
            name,
            help="show saved defaults"
            if name == "show"
            else "check configured paths without Docker",
        )
        a.add_argument("--workspace")
    attach = ws.add_parser(
        "attach", help="bind an existing run without executing or migrating it"
    )
    attach.add_argument("name")
    attach.add_argument("--workspace")
    attach.add_argument("--platform-root", required=True)
    attach.add_argument("--data-root", required=True)
    attach.add_argument("--project", action="append", required=True)
    attach.add_argument("--env-file")
    project = groups.add_parser(
        "project",
        help="register papers, select a default paper set, or author projects",
    )
    pa = project.add_subparsers(dest="action")
    for name in ("list", "use", "add", "remove"):
        a = pa.add_parser(
            name,
            help={
                "list": "list registered projects and defaults",
                "use": "select one or more papers together",
                "add": "register a project directory",
                "remove": "remove a registration, retaining all results",
            }[name],
        )
        a.add_argument("--workspace")
        if name == "use":
            a.add_argument("names", nargs="+")
        if name == "add":
            a.add_argument("name")
            a.add_argument("path")
        if name == "remove":
            a.add_argument("name")
    for name in ("create", "sync", "doctor", "test"):
        a = pa.add_parser(name, help="platform project " + name)
        _target(a, runs=False)
        a.add_argument("arguments", nargs=argparse.REMAINDER)
    infra = groups.add_parser(
        "infra", help="host, environment, Docker and managed resources"
    )
    ia = infra.add_subparsers(dest="action")
    for name in (
        "doctor",
        "build",
        "plan",
        "requirements",
        "env",
        "docker",
        "manage",
        "audit-finalization",
    ):
        a = ia.add_parser(name, help=name + " infrastructure")
        if name in ("docker", "env"):
            sub = a.add_subparsers(dest="infra_command")
            verbs = (
                ("doctor", "start", "status", "stop", "env")
                if name == "docker"
                else ("list", "show", "validate", "build", "control")
            )
            for verb in verbs:
                child = sub.add_parser(verb, help=verb + " " + name)
                _target(child, projects=False, runs=False)
                child.add_argument("arguments", nargs=argparse.REMAINDER)
        else:
            _target(a, projects=False, runs=False)
            a.add_argument("arguments", nargs=argparse.REMAINDER)

    from .parser import build_parser as forensic_parser

    original = forensic_parser()
    original_actions = next(
        a for a in original._actions if isinstance(a, argparse._SubParsersAction)
    ).choices
    diagnose = groups.add_parser(
        "diagnose", help="evidence, failures, runtime and telemetry"
    )
    dg = diagnose.add_subparsers(dest="diagnostic_group")
    diagnostic_groups = {
        "evidence": {
            "verify": "verify-evidence",
            "status": "status",
            "locate": "locate",
            "graph": "graph",
            "timeline": "timeline",
            "last-writer": "last-writer",
            "unclosed": "unclosed-operations",
            "index": "index-status",
            "rebuild": "rebuild-index",
        },
        "failure": {
            "why": "why",
            "snapshot": "debug-snapshot",
            "triage": "triage-plan",
            "catalog": "failure-catalog",
            "bundle": "crash-bundle",
            "verify-bundle": "crash-bundle-verify",
        },
        "runtime": {
            "status": "runtime-status",
            "recovery-plan": "runtime-recovery-plan",
        },
        "telemetry": {"query": "telemetry-query", "summary": "telemetry-summary"},
        "recovery": {"state": "recovery-state"},
        "release": {"verify": "release-verify"},
        "architecture": {"report": "architecture-report", "gate": "architecture-gate"},
    }
    for name, mapping in diagnostic_groups.items():
        node = dg.add_parser(name, help=name + " diagnostic tools")
        actions = node.add_subparsers(dest="diagnostic_action")
        for verb, internal in mapping.items():
            child = actions.add_parser(
                verb, parents=[original_actions[internal]], add_help=False
            )
            child.set_defaults(diagnostic_command=internal)
    dev = groups.add_parser(
        "dev", help="architecture and algorithm/concurrency/performance checks"
    )
    da = dev.add_subparsers(dest="action")
    for name in ("architecture", "algorithm", "concurrency", "performance", "boundary"):
        node = da.add_parser(name, help=name + " development checks")
        actions = node.add_subparsers(dest="dev_command")
        for verb in (
            ("gate",)
            if name == "architecture"
            else ("audit",)
            if name == "boundary"
            else ("scan", "gate", "baseline")
        ):
            child = actions.add_parser(verb, help=verb + " " + name)
            if name != "architecture":
                if name == "boundary":
                    child.add_argument("root", nargs="?", default=".")
                    child.add_argument("--skip-release-manifest", action="store_true")
                else:
                    child.add_argument("--root")
                if name != "boundary":
                    child.add_argument("--report")
                    child.add_argument("--git-executable")
                    child.add_argument("--source-revision")
                    if name == "algorithm":
                        child.add_argument("--exact", action="store_true")
    release = da.add_parser(
        "release", help="prepare, build, verify and publish an official release"
    )
    release.set_defaults(dev_command="release")
    release.add_argument(
        "arguments", nargs=argparse.REMAINDER, help="release workflow arguments"
    )
    return p


def print_help_path(parser, path):
    node = parser
    for component in path:
        children = next(
            (a for a in node._actions if isinstance(a, argparse._SubParsersAction)),
            None,
        )
        if children is None or component not in children.choices:
            parser.error("unknown help path: " + " ".join(path))
        node = children.choices[component]
    node.print_help()


PAPER_GUIDE = {
    "setup": (
        "Connect paths once",
        (
            "workspace init --project paper=/path/to/paper",
            "workspace doctor",
            "project list",
        ),
    ),
    "design": (
        "Create and validate a paper; define hypotheses, controls and metrics in Research",
        (
            "project create PAPER_ID PATH",
            "project doctor --project PAPER",
            "project test --project PAPER",
        ),
    ),
    "pilot": (
        "Freeze a small pilot configuration before spending formal-run compute",
        (
            "research preflight",
            "research versions capture --name pilot-code",
            "research runs start pilot-code",
        ),
    ),
    "formal": (
        "Choose committed versions and a formal study configuration",
        (
            "research runs compare PILOT FORMAL",
            "run --new --committed --name formal-v1",
            "research runs label formal-v1 formal",
        ),
    ),
    "observe": (
        "Read node evidence and launcher logs without changing the execution",
        ("research status", "research logs --lines 100", "research runs list"),
    ),
    "recover": (
        "Stop admission before a safe checkpoint; reconcile uncertain effects before retry",
        (
            "research drain --run RUN",
            "research inspect --run RUN",
            "research checkpoint --run RUN",
            "research checkpoints list --run RUN",
            "research resume --run RUN",
        ),
    ),
    "analyze": (
        "Use recorded outputs and provenance; labels do not establish scientific validity",
        (
            "research runs show RUN --json",
            "research versions show RUN --json",
            "research runs compare BASELINE METHOD",
        ),
    ),
    "write": (
        "Cite exact run/version identities and distinguish successful, failed and reused evidence",
        (
            "research runs label RUN manuscript",
            "research checkpoints list --run RUN",
            "research versions show RUN --json",
        ),
    ),
    "submit": (
        "Preserve reproducible versions and evidence before submission",
        (
            "research runs label RUN submission",
            "research versions compare PILOT FORMAL",
        ),
    ),
    "revise": (
        "Keep submitted runs; make fresh experiments for requested additional evidence",
        (
            "research runs rerun SUBMITTED --name reproduction",
            "run --new --revision platform=main --revision PAPER=main --name revision-v1",
        ),
    ),
    "archive": (
        "Retain source repositories, frozen worktrees, private configuration and authoritative state",
        (
            "research runs label RUN archived",
            "research runs list --json",
            "research runs show RUN --json",
        ),
    ),
}

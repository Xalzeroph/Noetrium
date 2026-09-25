from __future__ import annotations

import argparse
import math

from noetrium_platform.infrastructure.resources.directory.api import ManagedDirectoryKind

from .context import ManagementCommandContext
from .scope_args import add_scope_arguments, scope_from_args

GROUP = "dirs"


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "value must be a non-negative integer"
        ) from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError(
            "value must be a non-negative integer"
        )
    return parsed


def _non_negative_finite_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "value must be a finite non-negative number"
        ) from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError(
            "value must be a finite non-negative number"
        )
    return parsed


def register(groups) -> None:
    parser = groups.add_parser(GROUP)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("init")
    sub.add_parser("show")
    stats = sub.add_parser("stats")
    stats.add_argument("kind", choices=[kind.value for kind in ManagedDirectoryKind])
    entries = sub.add_parser("entries")
    entries.add_argument("kind", choices=[kind.value for kind in ManagedDirectoryKind])
    entries.add_argument("--limit", type=_non_negative_int, default=20)
    clean = sub.add_parser("clean")
    clean.add_argument("kind", choices=[ManagedDirectoryKind.CACHE.value, ManagedDirectoryKind.TEMP.value])
    clean.add_argument(
        "--older-than-seconds",
        type=_non_negative_finite_float,
    )
    clean.add_argument("--dry-run", action="store_true")
    create = sub.add_parser("workspace-create")
    create.add_argument("workspace_id")
    create.add_argument("--category", default="default")
    create.add_argument("--owner")
    create.add_argument("--note")
    add_scope_arguments(create)
    listing = sub.add_parser("workspace-list")
    listing.add_argument("--category")
    add_scope_arguments(listing)


def dispatch(args, context: ManagementCommandContext):
    directories = context.directories
    if args.action == "init":
        return directories.layout.ensure_layout()
    if args.action == "show":
        return directories.layout.layout
    if args.action == "stats":
        kind = ManagedDirectoryKind(args.kind)
        return {"content": directories.inspection.content_stats(kind), "filesystem": directories.inspection.usage(kind)}
    if args.action == "entries":
        return directories.inspection.entries(ManagedDirectoryKind(args.kind), limit=args.limit)
    if args.action == "clean":
        kind = ManagedDirectoryKind(args.kind)
        if args.dry_run:
            return directories.cleanup.clean_plan(kind, older_than_seconds=args.older_than_seconds)
        return directories.cleanup.clean(kind, older_than_seconds=args.older_than_seconds)
    if args.action == "workspace-create":
        return directories.workspaces.allocate_workspace(
            args.workspace_id, scope=scope_from_args(args), category=args.category, owner=args.owner, note=args.note
        )
    if args.action == "workspace-list":
        return directories.workspaces.list_workspaces(scope=scope_from_args(args), category=args.category)
    raise ValueError(f"unsupported directory management action: {args.action}")


__all__ = ["GROUP", "dispatch", "register"]

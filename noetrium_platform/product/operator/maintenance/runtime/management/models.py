from __future__ import annotations

from pathlib import Path

from noetrium_platform.capabilities.model.asset.api import ModelSourceSpec

from .context import ManagementCommandContext
from .scope_args import add_scope_arguments, scope_from_args

GROUP = "model"


def register(groups) -> None:
    parser = groups.add_parser(GROUP)
    sub = parser.add_subparsers(dest="action", required=True)
    add = sub.add_parser("add")
    add.add_argument("model_id")
    add.add_argument("source", type=Path)
    add.add_argument("--mode", default="reference", choices=("reference", "copy", "move", "symlink"))
    add.add_argument("--family", default="")
    add.add_argument("--notes", default="")
    add.add_argument("--tag", action="append", default=[])
    add.add_argument("--pool", default="default")
    add_scope_arguments(add)
    fetch = sub.add_parser("fetch")
    fetch.add_argument("model_id")
    fetch.add_argument("source")
    fetch.add_argument("--backend", default="huggingface")
    fetch.add_argument("--revision")
    fetch.add_argument("--include", action="append", default=[])
    fetch.add_argument("--exclude", action="append", default=[])
    fetch.add_argument("--max-workers", type=int)
    fetch.add_argument("--family", default="")
    fetch.add_argument("--notes", default="")
    fetch.add_argument("--tag", action="append", default=[])
    fetch.add_argument("--pool", default="default")
    fetch.add_argument("--no-resume", action="store_true")
    add_scope_arguments(fetch)
    listing = sub.add_parser("list")
    listing.add_argument("--tag", action="append", default=[])
    listing.add_argument("--family")
    sub.add_parser("sources")
    sub.add_parser("pools")
    inspect = sub.add_parser("inspect")
    inspect.add_argument("model_id")
    stats = sub.add_parser("stats")
    stats.add_argument("model_id")
    refs = sub.add_parser("refs")
    refs.add_argument("model_id")
    remove = sub.add_parser("remove")
    remove.add_argument("model_id")
    remove.add_argument("--delete-files", action="store_true")


def dispatch(args, context: ManagementCommandContext):
    assets = context.models.assets
    if args.action == "add":
        return assets.register_model(
            args.model_id,
            scope_from_args(args),
            args.source,
            mode=args.mode,
            family=args.family,
            notes=args.notes,
            tags=tuple(args.tag),
            storage_pool=args.pool,
        )
    if args.action == "fetch":
        return assets.fetch_model(
            args.model_id,
            scope_from_args(args),
            ModelSourceSpec(
                backend=args.backend,
                source=args.source,
                revision=args.revision,
                storage_pool=args.pool,
                include=tuple(args.include),
                exclude=tuple(args.exclude),
                resume=not args.no_resume,
                max_workers=args.max_workers,
            ),
            family=args.family,
            notes=args.notes,
            tags=tuple(args.tag),
        )
    if args.action == "list":
        return assets.models(tags=tuple(args.tag), family=args.family)
    if args.action == "sources":
        return assets.source_backends()
    if args.action == "pools":
        return assets.storage_pools()
    if args.action == "inspect":
        return {
            "asset": assets.model(args.model_id),
            "usage": assets.model_usage(args.model_id),
            "stats": assets.model_stats(args.model_id),
            "config": assets.model_config(args.model_id),
        }
    if args.action == "stats":
        return assets.model_stats(args.model_id)
    if args.action == "refs":
        return assets.model_usage(args.model_id)
    if args.action == "remove":
        return {"removed": assets.unregister_model(args.model_id, delete_managed_files=args.delete_files)}
    raise ValueError(f"unsupported model management action: {args.action}")


__all__ = ["GROUP", "dispatch", "register"]

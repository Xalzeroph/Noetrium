from __future__ import annotations

from noetrium_platform.composition.release_verification import verify_source_tree_release


def route_release(args: object):
    if getattr(args, "command", None) == "release-verify":
        return verify_source_tree_release(args.root, args.manifest)
    return None


__all__ = ["route_release"]

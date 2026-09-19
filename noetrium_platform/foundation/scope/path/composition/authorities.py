from ..runtime import TargetPathResolver


def build_target_path_resolver() -> TargetPathResolver:
    return TargetPathResolver()


__all__ = ["build_target_path_resolver"]

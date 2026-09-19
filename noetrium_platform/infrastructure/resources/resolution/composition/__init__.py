from ..runtime import LocalResourceResolver
from noetrium_platform.foundation.scope.path.composition import build_target_path_resolver


def build_local_resource_resolver() -> LocalResourceResolver:
    return LocalResourceResolver(build_target_path_resolver())


__all__ = ["build_local_resource_resolver"]

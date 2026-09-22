from noetrium_platform.foundation.scope.path.composition import build_target_path_resolver
from noetrium_platform.infrastructure.resources.resolution.runtime import LocalResourceResolver

def build_local_resource_resolver() -> LocalResourceResolver:
    return LocalResourceResolver(build_target_path_resolver())

__all__ = ["build_local_resource_resolver"]

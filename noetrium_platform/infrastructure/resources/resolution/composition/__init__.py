from ..runtime import LocalResourceResolver
from noetrium_platform.foundation.governance.api import ScopePathPort

def compose_local_resource_resolver(path_resolver: ScopePathPort) -> LocalResourceResolver:
    return LocalResourceResolver(path_resolver)

__all__ = ["compose_local_resource_resolver"]

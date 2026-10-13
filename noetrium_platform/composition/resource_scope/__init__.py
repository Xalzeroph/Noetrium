from noetrium_platform.infrastructure.resources.resolution.runtime import LocalResourceResolver


def build_local_resource_resolver() -> LocalResourceResolver:
    return LocalResourceResolver()


__all__ = ["build_local_resource_resolver"]

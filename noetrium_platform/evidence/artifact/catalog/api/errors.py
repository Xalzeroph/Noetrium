class ArtifactRegistryConflict(RuntimeError):
    pass


class ArtifactRegistryCorruptionError(RuntimeError):
    pass


class ArtifactNotFound(KeyError):
    pass


__all__ = ["ArtifactNotFound", "ArtifactRegistryConflict", "ArtifactRegistryCorruptionError"]

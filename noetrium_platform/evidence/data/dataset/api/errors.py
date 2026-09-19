class DatasetRegistryConflict(RuntimeError):
    pass


class DatasetRegistryCorruptionError(RuntimeError):
    pass


class DatasetNotFound(KeyError):
    pass


__all__ = ["DatasetNotFound", "DatasetRegistryConflict", "DatasetRegistryCorruptionError"]

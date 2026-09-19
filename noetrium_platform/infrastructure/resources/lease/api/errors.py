from __future__ import annotations


class ResourceOwnershipConflict(RuntimeError):
    """The same resource identity was registered with incompatible ownership."""


class ResourceLeaseConflict(RuntimeError):
    """A lease operation violates identity, exclusivity, generation, or fencing."""


class ResourceLeaseExpired(ResourceLeaseConflict):
    """The caller attempted to use or renew an expired lease."""


__all__ = ["ResourceLeaseConflict", "ResourceLeaseExpired", "ResourceOwnershipConflict"]

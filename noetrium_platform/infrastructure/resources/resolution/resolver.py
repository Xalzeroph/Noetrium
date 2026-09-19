from __future__ import annotations
from collections.abc import Callable
from typing import Generic, TypeVar
from noetrium_platform.foundation.scope.api import ScopeIdentity
from .contracts import ResolutionPolicy, ResolvedValue, ScopedValue

T=TypeVar("T")

class ResourceNotResolved(KeyError): pass
class ResourceResolutionConflict(RuntimeError): pass

class HierarchicalResourceResolver(Generic[T]):
    def __init__(self, *, ancestry:Callable[[ScopeIdentity],tuple[ScopeIdentity,...]], merge:Callable[[tuple[T,...]],T]|None=None) -> None:
        self._ancestry=ancestry; self._merge=merge; self._values:dict[tuple[str,str,str],ScopedValue[T]]={}
    def bind(self, item:ScopedValue[T])->None:
        key=(item.namespace,item.name,item.scope.key)
        old=self._values.get(key)
        if old is not None and old != item: raise ResourceResolutionConflict(key)
        self._values[key]=item
    def resolve(self, *, namespace:str, name:str, scope:ScopeIdentity)->ResolvedValue[T]:
        found:list[ScopedValue[T]]=[]
        for candidate in self._ancestry(scope):
            item=self._values.get((namespace,name,candidate.key))
            if item is None: continue
            found.append(item)
            if item.policy in {ResolutionPolicy.NO_INHERIT,ResolutionPolicy.OVERRIDE,ResolutionPolicy.INHERIT}: break
        if not found: raise ResourceNotResolved((namespace,name,scope.key))
        first=found[0]
        if first.policy is ResolutionPolicy.MERGE:
            if self._merge is None: raise ResourceResolutionConflict("merge policy requires merge function")
            value=self._merge(tuple(item.value for item in reversed(found)))
        else: value=first.value
        return ResolvedValue(namespace,name,scope,tuple(item.scope for item in found),value)

__all__=["HierarchicalResourceResolver","ResourceNotResolved","ResourceResolutionConflict"]

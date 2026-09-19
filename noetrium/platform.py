"""Stable product facade for applications built on Noetrium.

The implementation is owned by the product/operator composition layer. This
module is deliberately a forwarding surface so there is one composition owner
for the public platform bindings and no second facade implementation.
"""

from noetrium_platform.platform import *
from noetrium_platform.platform import __all__

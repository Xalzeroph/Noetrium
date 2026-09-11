from __future__ import annotations

import sys


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "nsh":
        from .nsh import main as nsh_main
        raise SystemExit(nsh_main(sys.argv[2:]))
    from noetrium_platform.product.operator.composition.research import main
    raise SystemExit(main())

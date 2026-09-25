from pathlib import Path
import json
import sys
from dataclasses import asdict

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from noetrium_platform.foundation.governance.architecture.report import build_architecture_report


def main()->int:
    report=build_architecture_report(ROOT)
    print(json.dumps(asdict(report),ensure_ascii=False,sort_keys=True,indent=2,default=str))
    return 0 if report.clean else 1

if __name__=='__main__': raise SystemExit(main())

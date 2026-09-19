from pathlib import Path
import json,sys
from dataclasses import asdict
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from noetrium_platform.foundation.governance.architecture.optimization import build_optimization_report
if __name__=='__main__':
    print(json.dumps(asdict(build_optimization_report(ROOT)),ensure_ascii=False,sort_keys=True,indent=2))

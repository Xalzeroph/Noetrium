from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from noetrium_platform.foundation.governance.quality import scan_no_degradation

def main()->int:
    findings=scan_no_degradation(ROOT)
    for x in findings: print(f"FAIL {x.kind} {x.path}:{x.line} {x.identifier}")
    if findings: return 1
    print("NO_DEGRADATION_AUDIT_PASS"); return 0
if __name__=='__main__': raise SystemExit(main())

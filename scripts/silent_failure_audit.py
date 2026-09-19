from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from noetrium_platform.foundation.governance.quality import scan_silent_failures


def main() -> int:
    findings = scan_silent_failures(ROOT / "noetrium_platform") + scan_silent_failures(ROOT / "projects")
    for f in findings:
        print(f"{f.kind} {f.path}:{f.line}: {f.detail}")
    if findings:
        print(f"SILENT_FAILURE_AUDIT_FAIL count={len(findings)}")
        return 1
    print("SILENT_FAILURE_AUDIT_PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

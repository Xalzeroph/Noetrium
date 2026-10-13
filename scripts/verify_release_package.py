from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from noetrium_platform.foundation.governance.release.runtime.package_verification import verify_release_package


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: verify_release_package.py RELEASE.zip")
        return 2
    report = verify_release_package(Path(args[0]))
    for error in report.errors:
        print(f"RELEASE_PACKAGE_VERIFY_FAIL {error}")
    if not report.clean:
        return 1
    print(f"RELEASE_PACKAGE_VERIFY_PASS manifest={report.manifest_digest} evidence={report.evidence_digest} files={report.file_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

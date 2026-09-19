import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from noetrium_platform.composition.release_verification import verify_persisted_release_authority
from noetrium_platform.foundation.governance.release.runtime.freeze_lock import ReleaseFreezeBusy, ReleaseFreezeLock


def _verify_locked(root: Path) -> int:
    report = verify_persisted_release_authority(root)
    for error in report.errors:
        print(f"RELEASE_EVIDENCE_VERIFY_FAIL {error}")
    if not report.clean:
        return 1
    print(f"RELEASE_MANIFEST_VERIFY_PASS {report.manifest_digest}")
    print(f"RELEASE_EVIDENCE_VERIFY_PASS {report.evidence_digest}")
    print(f"RELEASE_AUTHORITY_VERIFY_PASS {report.authority_digest}")
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify the persisted Noetrium release authority and evidence."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="repository root to verify (default: the project containing this script)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    root = _parse_args(argv).root.resolve()
    try:
        with ReleaseFreezeLock(root):
            return _verify_locked(root)
    except ReleaseFreezeBusy:
        print("RELEASE_EVIDENCE_VERIFY_FAIL another release freeze operation is already active")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

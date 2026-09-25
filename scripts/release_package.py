from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from noetrium_platform.composition.release_pipeline import build_release_pipeline
from noetrium_platform.foundation.governance.release.runtime.freeze_lock import ReleaseFreezeBusy, ReleaseFreezeLock


def main() -> int:
    try:
        with ReleaseFreezeLock(ROOT):
            result = build_release_pipeline().build(ROOT)
            print(
                f"ZIP={result.zip_path}\n"
                f"SHA256={result.sha256}\n"
                f"MANIFEST={result.manifest_digest}\n"
                f"EVIDENCE={result.evidence_digest}\n"
                f"FILES={result.file_count}"
            )
            return 0
    except ReleaseFreezeBusy:
        print("OFFICIAL_RELEASE_BLOCKED: another release freeze operation is already active")
        return 2
    except Exception as exc:
        print(f"OFFICIAL_RELEASE_BLOCKED: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

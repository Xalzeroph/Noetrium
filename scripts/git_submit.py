"""Portable repository submission controller.

The controller prefers the repository configured remote, but can recover from
missing SSH clients by switching to HTTPS or producing a bundle for transfer.
It deliberately keeps transport concerns outside research code.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=check)


def git(*args: str, check: bool = True):
    return run("git", *args, check=check)


def remote_url() -> str:
    return git("remote", "get-url", "origin").stdout.strip()


def normalize_https(url: str) -> str | None:
    if url.startswith("git@github.com:"):
        return "https://github.com/" + url.split(":", 1)[1]
    if url.startswith("ssh://git@github.com/"):
        return "https://github.com/" + url.split("github.com/", 1)[1]
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Submit repository changes through available transports")
    parser.add_argument("--branch", default="HEAD")
    parser.add_argument("--bundle", action="store_true", help="always create portable git bundle")
    args = parser.parse_args(argv)

    try:
        dirty = git("status", "--porcelain").stdout.strip()
        if dirty:
            print("SUBMIT_BLOCKED: working tree has uncommitted changes")
            return 2

        url = remote_url()
        if args.bundle:
            bundle = ROOT / "release_submission.bundle"
            git("bundle", "create", str(bundle), "--all")
            print(f"BUNDLE={bundle}")
            return 0

        ssh_missing = shutil.which("ssh") is None and url.startswith(("git@", "ssh://"))
        if ssh_missing:
            https = normalize_https(url)
            if https:
                git("remote", "set-url", "origin", https)
                url = https
                print("TRANSPORT=HTTPS_FALLBACK")

        result = git("push", "origin", args.branch, check=False)
        if result.returncode != 0:
            bundle = ROOT / "release_submission.bundle"
            git("bundle", "create", str(bundle), "--all")
            print("PUSH_FAILED_BUNDLE_CREATED")
            print(f"BUNDLE={bundle}")
            print(result.stderr.strip())
            return 2
        print("SUBMIT_OK")
        print(f"REMOTE={url}")
        return 0
    except Exception as exc:
        print(f"SUBMIT_ERROR={type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

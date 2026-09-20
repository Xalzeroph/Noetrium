from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "deploy" / "environments" / "catalog.json"
SCHEMA = "noetrium.environment-container-profiles.v1"
EXPECTED_PROFILES = frozenset({"minecraft", "embodied", "gui", "web", "software", "text_world"})
FORBIDDEN_IMAGE_MARKERS = (
    "copy research",
    "copy benchmarks",
    "openha",
    "osworld",
    "webarena",
    "libero",
    "calvin",
    "robotwin",
    "swe-bench",
)


def _load() -> dict:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise RuntimeError("environment profile catalog schema is not current")
    return data


def _profiles(data: dict) -> dict[str, dict]:
    rows = data.get("profiles")
    if not isinstance(rows, list):
        raise RuntimeError("environment profile catalog profiles must be a list")
    result: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("environment profile catalog entries must be objects")
        profile_id = row.get("profile_id")
        if not isinstance(profile_id, str) or not profile_id:
            raise RuntimeError("environment profile id must be non-empty")
        if profile_id in result:
            raise RuntimeError(f"duplicate environment profile: {profile_id}")
        result[profile_id] = row
    return result


def validate_catalog(data: dict, profiles: dict[str, dict]) -> dict:
    errors: list[str] = []
    if set(profiles) != EXPECTED_PROFILES:
        errors.append(
            "profile set drift: "
            f"expected={sorted(EXPECTED_PROFILES)!r} observed={sorted(profiles)!r}"
        )

    base = data.get("base")
    if not isinstance(base, dict):
        errors.append("base image authority must be an object")
    else:
        if base.get("build_mode") != "evidence-bound-wheel":
            errors.append("base image must remain evidence-bound-wheel")
        for field in ("dockerfile", "compose"):
            value = base.get(field)
            if not isinstance(value, str) or not value:
                errors.append(f"base {field} must be non-empty")
            elif not (ROOT / value).is_file():
                errors.append(f"base {field} does not exist: {value}")

    for profile_id, row in sorted(profiles.items()):
        if row.get("category_id") != profile_id:
            errors.append(
                f"{profile_id}: category_id must match canonical environment category"
            )
        if row.get("extends") != "base":
            errors.append(f"{profile_id}: environment profile must extend base")
        if profile_id == "text_world":
            if row.get("build_mode") != "base-only":
                errors.append("text_world must remain base-only")
            continue

        dockerfile_text = ""
        compose_text = ""
        for field in ("dockerfile", "compose"):
            value = row.get(field)
            if not isinstance(value, str) or not value:
                errors.append(f"{profile_id}: {field} must be non-empty")
                continue
            path = ROOT / value
            if not path.is_file():
                errors.append(f"{profile_id}: missing {field}: {value}")
                continue
            if field == "dockerfile":
                dockerfile_text = path.read_text(encoding="utf-8")
            else:
                compose_text = path.read_text(encoding="utf-8")

        if dockerfile_text:
            lowered = dockerfile_text.lower()
            if "arg platform_base_image" not in lowered:
                errors.append(f"{profile_id}: Dockerfile must declare PLATFORM_BASE_IMAGE")
            if "from ${platform_base_image}" not in lowered:
                errors.append(f"{profile_id}: Dockerfile must consume PLATFORM_BASE_IMAGE")
            for marker in FORBIDDEN_IMAGE_MARKERS:
                if marker in lowered:
                    errors.append(
                        f"{profile_id}: downstream/scientific marker leaked into image: {marker}"
                    )
        if compose_text:
            if "environment-doctor" not in compose_text:
                errors.append(f"{profile_id}: compose overlay lacks environment doctor")
            if profile_id not in compose_text:
                errors.append(f"{profile_id}: compose overlay lacks profile identity")

    if errors:
        raise RuntimeError("; ".join(errors))
    return {
        "schema": "noetrium.environment-profile-validation.v1",
        "status": "pass",
        "profile_count": len(profiles),
        "image_profile_count": sum(
            1 for row in profiles.values() if row.get("build_mode") != "base-only"
        ),
        "base_build_mode": data["base"]["build_mode"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    sub.add_parser("validate")
    show = sub.add_parser("show")
    show.add_argument("profile_id")
    args = parser.parse_args(argv)

    try:
        data = _load()
        profiles = _profiles(data)
        if args.command == "validate":
            print(json.dumps(validate_catalog(data, profiles), indent=2, sort_keys=True))
            return 0
        if args.command == "list":
            for profile_id in sorted(profiles):
                row = profiles[profile_id]
                print(
                    json.dumps(
                        {
                            "profile_id": profile_id,
                            "category_id": row["category_id"],
                            "build_mode": row.get(
                                "build_mode", "environment-image"
                            ),
                            "compose": row.get("compose"),
                        },
                        sort_keys=True,
                    )
                )
            return 0
        row = profiles[args.profile_id]
    except KeyError:
        print(f"unknown environment profile: {args.profile_id}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ENVIRONMENT_PROFILE_FAIL {type(exc).__qualname__}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(row, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

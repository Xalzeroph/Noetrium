#!/usr/bin/env python3
"""Read-only per-request Noetrium Raw Lake timing analysis.

The same lossless causal raw records drive both experimental evidence and
profiling; no second counter/measurement authority is invented. Stage timings
are nested: HTTP header/body/read are within http_transport, and the latter
plus release are within submit_and_completion_wait.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
from statistics import mean
from typing import Any


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError('percentile of empty sequence')
    pos = (len(ordered) - 1) * quantile
    lower = int(pos)
    weight = pos - lower
    return ordered[lower] * (1 - weight) + ordered[min(lower + 1, len(ordered) - 1)] * weight


def summary(values: list[float]) -> dict[str, int | float]:
    return {
        'count': len(values),
        'mean_seconds': round(mean(values), 4),
        'p50_seconds': round(_percentile(values, .5), 4),
        'p95_seconds': round(_percentile(values, .95), 4),
        'max_seconds': round(max(values), 4),
    }


def analyze(root: Path, *, limit: int = 0) -> dict[str, Any]:
    family = 'llm.attempt.raw'
    digest = hashlib.sha256(family.encode('utf-8')).hexdigest()
    files = sorted(root.rglob(f'family-{digest}.jsonl'))
    buckets: dict[str, list[float]] = defaultdict(list)
    stage_buckets: dict[str, list[float]] = defaultdict(list)
    requests: list[dict[str, Any]] = []
    for file in files:
        with file.open('r', encoding='utf-8') as f:
            for line in f:
                if not line.endswith('\n'):
                    # A concurrent writer's current incomplete tail is not a receipt.
                    continue
                try:
                    row = json.loads(line)
                    rec = row['payload']['__record']['payload']
                    data, capture = rec['data'], rec['capture']
                    dim = capture['dimensions']
                    elapsed = dim['duration_ns'] / 1e9
                    if elapsed < 0:
                        continue
                    timings = dim.get('stage_timings_ns') or {}
                    if not isinstance(timings, dict):
                        timings = {}
                    stage_s = {
                        k: v / 1e9 for k, v in timings.items()
                        if isinstance(k, str) and type(v) is int and v >= 0
                    }
                    entry = {
                        'request_id': data.get('request_id', ''),
                        'model': data.get('model', ''),
                        'deployment': data.get('endpoint', ''),
                        'duration_seconds': round(elapsed, 4),
                        'stages_seconds': {k: round(v, 4) for k, v in sorted(stage_s.items())},
                    }
                    requests.append(entry)
                    buckets[str(entry['deployment'])].append(elapsed)
                    for k, v in stage_s.items():
                        stage_buckets[k].append(v)
                except (ValueError, TypeError, KeyError, IndexError):
                    # Old formats may not carry the newer profile projection.
                    continue
    total = [x['duration_seconds'] for x in requests]
    return {
        'raw_segments': len(files),
        'request_count': len(requests),
        'overall': summary(total) if total else None,
        'by_deployment': {k: summary(v) for k, v in sorted(buckets.items())},
        'stages_nested_not_additive': {k: summary(v) for k, v in sorted(stage_buckets.items())},
        'slowest_requests': sorted(requests, key=lambda x: x['duration_seconds'], reverse=True)[:limit],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_root', type=Path, help='an existing run data root, read only')
    parser.add_argument('--slowest', type=int, default=3)
    args = parser.parse_args()
    if not args.run_root.is_dir() or args.slowest < 0:
        parser.error('run_root must be an existing directory; --slowest must be nonnegative')
    print(json.dumps(analyze(args.run_root, limit=args.slowest), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

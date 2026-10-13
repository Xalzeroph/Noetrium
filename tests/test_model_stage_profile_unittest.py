"""Regression for read-only Raw Lake request-stage analysis."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.profile_model_stages import analyze


class ModelStageProfileTests(unittest.TestCase):
    def test_latest_and_legacy_records_share_one_truth_with_nested_stages(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            name = 'family-' + hashlib.sha256(b'llm.attempt.raw').hexdigest() + '.jsonl'
            path = base / 'run-a' / name
            path.parent.mkdir()
            def event(nanos, stages=None):
                return {'payload': {'__record': {'payload': {
                    'data': {'request_id': f'req-{nanos}', 'endpoint': 'deployment', 'model': 'qwen'},
                    'capture': {'dimensions': {
                        'duration_ns': nanos,
                        **({} if stages is None else {'stage_timings_ns': stages}),
                    }},
                }}}}
            path.write_text(''.join(json.dumps(row) + '\n' for row in (
                event(5_000_000_000),
                event(9_000_000_000, {'http_headers_wait': 6_000_000_000, 'authority_release': 1_000_000_000}),
            )) + '{incomplete', encoding='utf-8')
            report = analyze(base, limit=1)
            self.assertEqual(report['request_count'], 2)
            self.assertEqual(report['overall']['mean_seconds'], 7.0)
            self.assertEqual(report['raw_segments'], 1)
            self.assertEqual(report['stages_nested_not_additive']['authority_release']['mean_seconds'], 1.0)
            self.assertEqual(report['stages_nested_not_additive']['http_headers_wait']['mean_seconds'], 6.0)
            self.assertEqual(report['slowest_requests'][0]['duration_seconds'], 9.0)


if __name__ == '__main__':
    unittest.main()

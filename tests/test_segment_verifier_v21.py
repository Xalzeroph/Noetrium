from pathlib import Path
import tempfile
import unittest
from noetrium_platform.infrastructure.reliability.forensics.providers import SegmentedHashChainedJSONL
from noetrium_platform.infrastructure.reliability.forensics.providers.segment_verifier import scan_segment_chain

class SegmentVerifierV21Tests(unittest.TestCase):
    def test_pure_scanner_matches_writer_tail_without_manifest_write(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'events'; log=SegmentedHashChainedJSONL(root,max_segment_bytes=220)
            for i in range(30): log.append({'i':i,'x':'y'*20})
            self.assertFalse((root/'manifest.json').exists())
            result=scan_segment_chain(root); self.assertEqual(result.total_rows,30); self.assertEqual(result.tail_hash,log.cached_tail[1]); self.assertFalse((root/'manifest.json').exists())

class VerifiedLedgerSliceContractTests(unittest.TestCase):
    def test_single_file_ledger_exposes_named_verified_cut(self):
        from noetrium_platform.infrastructure.reliability.forensics.providers import HashChainedJSONL

        with tempfile.TemporaryDirectory() as td:
            log = HashChainedJSONL(Path(td) / "failures.jsonl")
            for index in range(5):
                log.append({"index": index})
            verified = log.verified_payloads_after(2)
            self.assertEqual(verified.start_after, 2)
            self.assertEqual(verified.total_rows, 5)
            self.assertEqual([row["index"] for row in verified.payloads], [2, 3, 4])
            self.assertEqual(verified.tail_hash, log.cached_tail[1])
            self.assertEqual(len(verified.checkpoint_hash), 64)


    def test_single_file_verified_cut_streams_fixed_bounded_batches(self):
        from noetrium_platform.infrastructure.reliability.forensics.providers import HashChainedJSONL

        with tempfile.TemporaryDirectory() as td:
            log = HashChainedJSONL(Path(td) / "failures.jsonl")
            for index in range(10):
                log.append({"index": index})
            cut = log.verified_cut_after(3)
            log.append({"index": 10})
            batches = list(log.iter_verified_payload_batches(cut, batch_size=2))
            self.assertTrue(all(1 <= len(batch) <= 2 for batch in batches))
            self.assertEqual(
                [row["index"] for batch in batches for row in batch],
                list(range(3, 10)),
            )
            self.assertEqual(cut.total_rows, 10)
            self.assertEqual(cut.suffix_rows, 7)

    def test_single_file_stream_rejects_prefix_changed_after_verified_cut(self):
        from noetrium_platform.infrastructure.reliability.forensics.providers import HashChainError, HashChainedJSONL

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "failures.jsonl"
            log = HashChainedJSONL(path)
            for index in range(6):
                log.append({"index": index})
            cut = log.verified_cut_after(2)
            raw = path.read_bytes()
            path.write_bytes(raw.replace(b'"index":0', b'"index":9', 1))
            with self.assertRaises(HashChainError):
                list(log.iter_verified_payload_batches(cut, batch_size=2))

    def test_contract_rejects_incoherent_row_count_or_digest(self):
        from noetrium_platform.infrastructure.reliability.forensics.api import VerifiedLedgerSlice

        with self.assertRaises(ValueError):
            VerifiedLedgerSlice(2, 1, "0" * 64, "0" * 64, ())
        with self.assertRaises(ValueError):
            VerifiedLedgerSlice(0, 0, "INVALID", "0" * 64, ())

if __name__=='__main__': unittest.main()

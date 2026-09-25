from tests._concurrency_support import process_capture
from pathlib import Path
import json, tempfile, unittest
from unittest.mock import patch

from tests._concurrency_support import segmented_byte_capture
from noetrium_platform.infrastructure.lifecycle.process.api import CaptureIntegrityError
from noetrium_platform.infrastructure.lifecycle.process.capture.storage import CaptureStorage


class ProcessCaptureV53Tests(unittest.TestCase):
    def test_rotation_receipt_and_hot_tail(self):
        with tempfile.TemporaryDirectory() as td:
            cap=segmented_byte_capture(Path(td),'stdout',max_segment_bytes=10,fsync_every_bytes=100,tail_bytes=16)
            rotations=cap.append(b'abcdefghijklmnopqrstuvwxyz')
            self.assertEqual([(r.from_index,r.to_index) for r in rotations],[(0,1),(1,2)])
            self.assertEqual(cap.tail(),b'klmnopqrstuvwxyz')
            receipt=cap.sync(); self.assertEqual(receipt.total_bytes,26); self.assertEqual(len(receipt.tail_sha256),64)
            cap.close()


    def test_reopen_uses_resume_checkpoint_without_history_scan(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cap = segmented_byte_capture(
                root, 'stdout', max_segment_bytes=4, fsync_every_bytes=64, tail_bytes=8
            )
            cap.append(b'abcdefghijkl')
            cap.sync()
            cap.close()
            self.assertTrue((root / 'stdout.resume.json').is_file())

            with patch.object(
                CaptureStorage, 'sized_files', side_effect=AssertionError('history scan used')
            ):
                reopened = segmented_byte_capture(
                    root, 'stdout', max_segment_bytes=4, fsync_every_bytes=64, tail_bytes=8
                )
                self.assertEqual(reopened.tail(), b'efghijkl')
                reopened.append(b'mn')
                self.assertEqual(reopened.seal().total_bytes, 14)

    def test_stale_resume_checkpoint_rebuilds_from_append_only_disk(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cap = segmented_byte_capture(
                root, 'stderr', max_segment_bytes=8, fsync_every_bytes=64, tail_bytes=8
            )
            cap.append(b'abcdef')
            cap.sync()
            cap.close()
            with (root / 'stderr.000000.bin').open('ab') as handle:
                handle.write(b'GH')

            reopened = segmented_byte_capture(
                root, 'stderr', max_segment_bytes=8, fsync_every_bytes=64, tail_bytes=8
            )
            self.assertEqual(reopened.tail(), b'abcdefGH')
            self.assertEqual(reopened.writer.state.total_bytes, 8)
            document = json.loads((root / 'stderr.resume.json').read_text(encoding='utf-8'))
            self.assertEqual(document['total_bytes'], 8)
            reopened.close()

    def test_corrupt_resume_checkpoint_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cap = segmented_byte_capture(root, 'stdout', tail_bytes=8)
            cap.append(b'abc')
            cap.sync()
            cap.close()
            path = root / 'stdout.resume.json'
            document = json.loads(path.read_text(encoding='utf-8'))
            document['resume_sha256'] = '0' * 64
            path.write_text(json.dumps(document), encoding='utf-8')
            with self.assertRaisesRegex(CaptureIntegrityError, 'resume checkpoint digest mismatch'):
                segmented_byte_capture(root, 'stdout', tail_bytes=8)

    def test_reopen_recovers_tail_and_continues_append(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); cap=segmented_byte_capture(root,'stderr',tail_bytes=8); cap.append(b'1234567890'); cap.sync(); cap.close()
            cap2=segmented_byte_capture(root,'stderr',tail_bytes=8); self.assertEqual(cap2.tail(),b'34567890'); cap2.append(b'AB'); self.assertEqual(cap2.tail(),b'567890AB'); self.assertEqual(cap2.seal().total_bytes,12)

if __name__=='__main__': unittest.main()

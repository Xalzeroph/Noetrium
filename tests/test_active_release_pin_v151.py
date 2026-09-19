from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import multiprocessing as mp
import unittest

from noetrium_platform.foundation.governance.release.runtime.active_pin_store import ActiveReleasePinStore
from noetrium_platform.foundation.governance.release.api import ActiveReleasePinned


def acquire_pin(root: str, q) -> None:
    store=ActiveReleasePinStore(Path(root))
    pin=store.acquire("ctl","a"*64,"b"*64)
    q.put((pin.control_id,pin.runtime_manifest_digest,pin.release_digest))


class ActiveReleasePinTests(unittest.TestCase):
    def test_pin_is_idempotent_and_requires_explicit_release(self):
        with TemporaryDirectory() as td:
            store=ActiveReleasePinStore(Path(td))
            first=store.acquire("ctl","a"*64,"b"*64)
            second=store.acquire("ctl","a"*64,"b"*64)
            self.assertEqual(first,second)
            with self.assertRaises(ActiveReleasePinned): store.assert_unpinned("b"*64)
            store.release("ctl","a"*64)
            store.assert_unpinned("b"*64)

    def test_cross_process_same_pin_converges_to_one_document(self):
        with TemporaryDirectory() as td:
            ctx=mp.get_context("spawn"); q=ctx.Queue()
            ps=[ctx.Process(target=acquire_pin,args=(td,q)) for _ in range(4)]
            for p in ps: p.start()
            for p in ps: p.join(10); self.assertEqual(p.exitcode,0)
            rows=[q.get(timeout=2) for _ in ps]
            self.assertEqual(len(set(rows)),1)
            self.assertEqual(len(ActiveReleasePinStore(Path(td)).all()),1)


if __name__=='__main__': unittest.main()

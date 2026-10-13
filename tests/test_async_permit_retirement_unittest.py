"""Completion fence: a slow Resource Authority permit release never stalls ASYNC_IO."""
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event, Lock
from time import perf_counter, sleep
import unittest

from noetrium_platform.foundation.kernel.concurrency.runtime.execution import _CompletionFencedHandle


class _BlockingProvider:
    def __init__(self, pool):
        self.pool = pool
    def submit_inherited_retirement(self, fn):
        return self.pool.submit(fn)


class AsyncPermitRetirementTests(unittest.TestCase):
    def test_long_authority_release_does_not_block_completion_callback(self):
        released = []
        raw = Future()
        with ThreadPoolExecutor(max_workers=1) as executor:
            def release():
                sleep(.25)
                released.append(1)
            fence = _CompletionFencedHandle(
                raw, release, blocking_release_provider=_BlockingProvider(executor)
            )
            begin = perf_counter()
            raw.set_result('ok')
            callback_time = perf_counter() - begin
            self.assertLess(callback_time, .12, 'model event-loop callback blocked on durable Authority')
            self.assertEqual(fence.result(timeout=2), 'ok')
            self.assertEqual(released, [1])

    def test_cancelled_release_worker_gets_exactly_once_fallback(self):
        start, finish = Event(), Event()
        with ThreadPoolExecutor(max_workers=1) as executor:
            def occupy():
                start.set()
                finish.wait(2)
            occupant=executor.submit(occupy)
            self.assertTrue(start.wait(2))
            class Provider:
                child = None
                def submit_inherited_retirement(self, fn):
                    self.child = executor.submit(fn)
                    return self.child
            provider=Provider()
            raw=Future()
            released=[]
            fence=_CompletionFencedHandle(
                raw, lambda:released.append('retired'),
                blocking_release_provider=provider
            )
            raw.set_result(17)
            self.assertTrue(provider.child.cancel())
            self.assertEqual(fence.result(timeout=1), 17)
            self.assertEqual(released,['retired'])
            finish.set()
            occupant.result(timeout=2)

    def test_full_worker_capacity_falls_back_to_fail_closed_release(self):
        class Saturated:
            def submit_inherited_retirement(self, fn):
                raise RuntimeError("worker provider already closed")
        raw=Future()
        released=[]
        fence=_CompletionFencedHandle(raw,lambda:released.append(1),
                                     blocking_release_provider=Saturated())
        raw.set_result('done')
        self.assertEqual(fence.result(timeout=1),'done')
        self.assertEqual(released,[1])


if __name__=='__main__':
    unittest.main()

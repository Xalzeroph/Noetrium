"""A concurrent HTTP batch owns one event-loop lag timer, not one per request."""
from __future__ import annotations

import asyncio
import time

from noetrium_platform.capabilities.model.serving.endpoint.providers.http_pool import (
    _HttpEventLoopLagProbe,
)


def test_concurrent_http_probes_share_one_timer_and_detach_without_leaks():
    async def run():
        probes = tuple(_HttpEventLoopLagProbe() for _ in range(32))
        first_clock = probes[0]._clock
        assert len(first_clock._observers) == len(probes)
        assert all(probe._clock is first_clock for probe in probes)
        assert len(_HttpEventLoopLagProbe._CLOCKS) == 1
        handle = first_clock._handle

        for probe in probes[:-1]:
            probe.stop()
        assert not handle.cancelled()
        assert len(first_clock._observers) == 1

        await asyncio.sleep(.06)
        time.sleep(.11)  # Simulate blocking work unrelated to HTTP.
        await asyncio.sleep(.02)

        maximum, accumulated = probes[-1].stop()
        assert maximum > 50_000_000
        assert accumulated >= maximum
        assert first_clock._handle.cancelled()
        assert not first_clock._observers
        assert len(_HttpEventLoopLagProbe._CLOCKS) == 0

    asyncio.run(run())


def test_separate_event_loops_do_not_reuse_stale_lag_observers():
    def observe():
        async def run():
            probe = _HttpEventLoopLagProbe()
            clock = probe._clock
            result = probe.stop()
            return clock._loop.is_running(), result

        return asyncio.run(run())

    assert observe() == (True, (0, 0))
    assert observe() == (True, (0, 0))
    assert len(_HttpEventLoopLagProbe._CLOCKS) == 0


def test_loop_thread_cpu_evidence_is_exact_and_not_request_attribution():
    import pytest

    async def run():
        probe = _HttpEventLoopLagProbe()
        with pytest.raises(RuntimeError, match="not complete"):
            _ = probe.loop_thread_cpu_observed_ns
        start_thread_cpu = time.thread_time_ns()
        while time.thread_time_ns() - start_thread_cpu < 7_000_000:
            pass
        probe.stop()
        # The metric is CPU spent on this event-loop OS thread during the
        # observation interval, including all concurrent requests. It is not
        # an exclusive accounting of the individual model request's work.
        assert probe.loop_thread_cpu_observed_ns >= 7_000_000
        assert not probe._clock._observers
    asyncio.run(run())


def test_shared_lag_prefix_and_monotone_max_equal_per_request_sampling():
    """Reference implementation uses O(Q) work per event; optimized is exact."""
    from random import Random

    async def run():
        generator = Random(178311)
        probes = []
        samples: list[int] = []
        live: dict[_HttpEventLoopLagProbe, int] = {}
        first = _HttpEventLoopLagProbe()
        clock = first._clock
        live[first] = 0
        # Deterministic boundary: no synthetic final observation between ticks.
        clock._lateness_ns = lambda: 0
        for step in range(500):
            lag = generator.randrange(1_000_000, 220_000_000)
            sampled = lag if lag > clock._SCHEDULER_TOLERANCE_NS else 0
            samples.append(sampled)
            clock._record_lag(lag)
            if step % 5 == 0:
                more = _HttpEventLoopLagProbe()
                assert more._clock is clock
                live[more] = len(samples)
            if step % 3 == 0 and len(live) > 1:
                observed = next(iter(live))
                began = live.pop(observed)
                expected = tuple(value for value in samples[began:] if value)
                maximum, accumulated = observed.stop()
                assert maximum == (max(expected) if expected else 0)
                assert accumulated == sum(expected)
        for observer, began in tuple(live.items()):
            expected = tuple(value for value in samples[began:] if value)
            maximum, accumulated = observer.stop()
            assert maximum == (max(expected) if expected else 0)
            assert accumulated == sum(expected)
        assert not clock._observers
        assert not clock._maxima
        assert clock._handle.cancelled()

    asyncio.run(run())


def test_request_detach_includes_only_its_own_between_tick_lateness():
    async def run():
        first, second = _HttpEventLoopLagProbe(), _HttpEventLoopLagProbe()
        clock = first._clock
        clock._lateness_ns = lambda: 78_000_000
        assert first.stop() == (78_000_000, 78_000_000)
        clock._lateness_ns = lambda: 0
        assert second.stop() == (0, 0)
    asyncio.run(run())

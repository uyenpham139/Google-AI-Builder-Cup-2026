import asyncio
from types import SimpleNamespace

import pytest

from app.api.websockets import audio
from app.services.call_analysis import CallAnalysisWorker


@pytest.mark.asyncio
async def test_burst_is_combined_before_first_analysis():
    calls = []
    done = asyncio.Event()

    async def analyze(window, trigger):
        calls.append((window, trigger))
        done.set()

    worker = CallAnalysisWorker(analyze, debounce_seconds=0.01)
    try:
        worker.submit("first", "first")
        worker.submit("first second", "second")
        worker.update_context("first second benign clarification")
        await asyncio.wait_for(done.wait(), 1)
        assert calls == [("first second benign clarification", "second")]
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_slow_analysis_keeps_only_latest_followup_and_never_overlaps():
    calls = []
    started = asyncio.Event()
    release = asyncio.Event()
    followup_done = asyncio.Event()
    active = 0
    max_active = 0

    async def analyze(window, trigger):
        nonlocal active, max_active
        active += 1
        max_active = max(active, max_active)
        calls.append((window, trigger))
        try:
            if len(calls) == 1:
                started.set()
                await release.wait()
            else:
                followup_done.set()
        finally:
            active -= 1

    worker = CallAnalysisWorker(analyze, debounce_seconds=0)
    try:
        worker.submit("first", "first")
        await asyncio.wait_for(started.wait(), 1)
        assert not worker.submit("first", "duplicate")
        worker.submit("first second", "second")
        worker.submit("first second third", "third")
        release.set()
        await asyncio.wait_for(followup_done.wait(), 1)
        assert calls == [("first", "first"), ("first second third", "third")]
        assert max_active == 1
        assert not worker.submit("first second third", "duplicate")
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_disconnect_cancels_analysis_and_drops_pending_work():
    started = asyncio.Event()
    cancelled = asyncio.Event()
    calls = []

    async def analyze(window, trigger):
        calls.append(window)
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    worker = CallAnalysisWorker(analyze, debounce_seconds=0)
    worker.submit("first", "first")
    await asyncio.wait_for(started.wait(), 1)
    worker.submit("second", "second")
    await worker.close()
    assert cancelled.is_set()
    assert calls == ["first"]


def test_duplicate_transcript_does_not_inflate_history_but_later_repetition_is_allowed(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(audio, "time", SimpleNamespace(monotonic=lambda: now[0], time=lambda: now[0]))
    state = audio.CallSessionState("test-dedup")
    assert state.add_transcript("Wire money now", "caller")
    now[0] += 0.1
    assert not state.add_transcript("  WIRE  money now  ", "caller")
    assert len(state.transcript_history) == 1
    now[0] += 3
    assert state.add_transcript("Wire money now", "caller")
    assert state.add_transcript("Wire money now", "callee")
    assert len(state.transcript_history) == 3

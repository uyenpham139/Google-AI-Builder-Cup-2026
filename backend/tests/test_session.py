import asyncio

import pytest

from app.services.ingestion.registry import SessionRegistry
from app.services.ingestion.session import AudioSessionContext


@pytest.mark.asyncio
async def test_chunks_reach_buffer_and_stream():
    ctx = AudioSessionContext("s1")
    await ctx.push_chunk(b"\x01\x02" * 1600)
    await ctx.push_chunk(b"\x03\x04" * 1600)
    gen = ctx.vertex_ai_stream_generator()
    assert await anext(gen) == b"\x01\x02" * 1600
    assert await anext(gen) == b"\x03\x04" * 1600
    assert ctx.get_latest_window(100)[-4:] == b"\x03\x04\x03\x04"
    ctx.terminate()


@pytest.mark.asyncio
async def test_full_queue_drops_oldest_not_newest():
    ctx = AudioSessionContext("s1", queue_size=2)
    for n in (1, 2, 3):
        await ctx.push_chunk(bytes([n, 0]))
    gen = ctx.vertex_ai_stream_generator()
    assert await anext(gen) == bytes([2, 0])
    assert await anext(gen) == bytes([3, 0])
    assert ctx.dropped_chunks == 1
    ctx.terminate()


@pytest.mark.asyncio
async def test_terminate_clears_buffer_ends_stream_and_is_idempotent():
    ctx = AudioSessionContext("s1", queue_size=2)
    for n in (1, 2, 3, 4):  # queue is full when terminate runs
        await ctx.push_chunk(bytes([n, 0]))
    ctx.terminate()
    ctx.terminate()
    assert ctx.is_active is False
    assert ctx.ring_buffer.size == 0
    assert ctx.get_latest_window(100) == b""
    assert [c async for c in ctx.vertex_ai_stream_generator()] == []


@pytest.mark.asyncio
async def test_push_after_terminate_is_ignored():
    ctx = AudioSessionContext("s1")
    ctx.terminate()
    await ctx.push_chunk(b"\x01\x00")
    assert ctx.ring_buffer.size == 0


@pytest.mark.asyncio
async def test_consumer_waiting_is_released_by_terminate():
    ctx = AudioSessionContext("s1")
    task = asyncio.create_task(anext(ctx.vertex_ai_stream_generator()))
    await asyncio.sleep(0)
    ctx.terminate()
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(task, timeout=1)


def test_registry_register_get_remove():
    reg = SessionRegistry()
    a = AudioSessionContext("same")
    reg.register(a)
    assert reg.get("same") is a and len(reg) == 1
    reg.remove(a)
    assert reg.get("same") is None and len(reg) == 0


def test_registry_replaces_and_terminates_old_session():
    reg = SessionRegistry()
    old, new = AudioSessionContext("same"), AudioSessionContext("same")
    reg.register(old)
    reg.register(new)
    assert old.is_active is False
    assert reg.get("same") is new
    reg.remove(old)  # stale teardown must not evict the new session
    assert reg.get("same") is new

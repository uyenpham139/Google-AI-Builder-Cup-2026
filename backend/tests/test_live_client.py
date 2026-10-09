import asyncio
import time

import pytest
from conftest import go_away, resumption

from app.services.gemini_live.client import GeminiLiveClient, GeminiLiveError
from app.services.gemini_live.config import LiveSettings

SETTINGS = LiveSettings(api_key="test-key")


def make_client(fake_live, **kw):
    return GeminiLiveClient(settings=SETTINGS, connect_fn=fake_live.connect, **kw)


@pytest.mark.asyncio
async def test_connect_configures_audio_session(fake_live):
    client = make_client(fake_live)
    await client.connect()
    try:
        assert client.is_connected
        assert fake_live.models == ["gemini-3.8-live"]
        cfg = fake_live.configs[0]
        assert [str(m).split(".")[-1].upper() for m in cfg.response_modalities] == ["AUDIO"]
        assert cfg.speech_config.voice_config.prebuilt_voice_config.voice_name == "Puck"
        assert cfg.context_window_compression is not None
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_send_audio_packs_pcm_blob(fake_live):
    client = make_client(fake_live)
    await client.connect()
    try:
        chunk = bytes(range(256)) * 12 + bytes(128)  # 3200 bytes = 100 ms @ 16 kHz
        assert len(chunk) == 3200
        assert await client.send_audio(chunk) is True
        blob = fake_live.sessions[0].sent[0]["audio"]
        assert blob.data == chunk
        assert blob.mime_type == "audio/pcm;rate=16000"
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_send_before_connect_is_dropped(fake_live):
    client = make_client(fake_live)
    assert await client.send_audio(bytes(3200)) is False
    assert client.dropped_chunks == 1


@pytest.mark.asyncio
async def test_empty_chunk_is_not_sent(fake_live):
    client = make_client(fake_live)
    await client.connect()
    try:
        assert await client.send_audio(b"") is False
        assert fake_live.sessions[0].sent == []
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_odd_length_chunk_is_not_sent(fake_live):
    client = make_client(fake_live)
    await client.connect()
    try:
        assert await client.send_audio(b"\x00\x01\x02") is False
        assert fake_live.sessions[0].sent == []
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_send_overhead_under_15ms(fake_live):
    client = make_client(fake_live)
    await client.connect()
    try:
        chunk = bytes(3200)
        start = time.perf_counter()
        for _ in range(200):
            await client.send_audio(chunk)
        avg_ms = (time.perf_counter() - start) / 200 * 1000
        assert avg_ms < 15
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_disconnect_closes_session_and_is_idempotent(fake_live):
    client = make_client(fake_live)
    await client.connect()
    await client.disconnect()
    await client.disconnect()
    assert fake_live.sessions[0].closed is True
    assert client.is_connected is False
    assert await client.send_audio(bytes(3200)) is False


@pytest.mark.asyncio
async def test_missing_api_key_raises():
    client = GeminiLiveClient(settings=LiveSettings(api_key=None))
    with pytest.raises(GeminiLiveError, match="GEMINI_API_KEY"):
        await client.connect()


@pytest.mark.asyncio
async def test_handshake_failure_wrapped(fake_live):
    fake_live.fail_next = 1
    client = make_client(fake_live)
    with pytest.raises(GeminiLiveError):
        await client.connect()
    assert client.is_connected is False


@pytest.mark.asyncio
async def test_reconnects_with_latest_resumption_handle(fake_live, wait_until):
    client = make_client(fake_live, backoff=(0, 0, 0))
    await client.connect()
    try:
        first = fake_live.sessions[0]
        await first.inbox.put(resumption("h1"))
        await first.inbox.put(resumption("h2"))
        await first.inbox.put(ConnectionError("socket dropped"))
        await wait_until(lambda: client.reconnect_count == 1)
        assert len(fake_live.sessions) == 2
        assert fake_live.configs[1].session_resumption.handle == "h2"
        assert client.is_connected
        assert await client.send_audio(bytes(3200)) is True
        assert len(fake_live.sessions[1].sent) == 1
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_non_resumable_update_does_not_replace_handle(fake_live, wait_until):
    client = make_client(fake_live, backoff=(0,))
    await client.connect()
    try:
        first = fake_live.sessions[0]
        await first.inbox.put(resumption("good"))
        await first.inbox.put(resumption("bad", resumable=False))
        await first.inbox.put(ConnectionError("x"))
        await wait_until(lambda: client.reconnect_count == 1)
        assert fake_live.configs[1].session_resumption.handle == "good"
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_go_away_triggers_proactive_reconnect(fake_live, wait_until):
    client = make_client(fake_live, backoff=(0,))
    await client.connect()
    try:
        await fake_live.sessions[0].inbox.put(go_away())
        await wait_until(lambda: client.reconnect_count == 1)
        assert fake_live.sessions[0].closed is True
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_stream_end_with_no_messages_reconnects_not_spins(fake_live, wait_until):
    client = make_client(fake_live, backoff=(0,))
    await client.connect()
    try:
        await fake_live.sessions[0].inbox.put(None)
        await wait_until(lambda: client.reconnect_count == 1)
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_turn_end_with_messages_keeps_session(fake_live):
    client = make_client(fake_live, backoff=(0,))
    await client.connect()
    try:
        s = fake_live.sessions[0]
        await s.inbox.put(resumption("h1"))
        await s.inbox.put(None)
        await asyncio.sleep(0.05)
        assert client.reconnect_count == 0
        assert len(fake_live.sessions) == 1
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_audio_dropped_while_reconnecting(fake_live, wait_until):
    client = make_client(fake_live, backoff=(0.05, 0.05))
    await client.connect()
    fake_live.fail_next = 1  # first reconnect attempt fails, second succeeds
    try:
        await fake_live.sessions[0].inbox.put(ConnectionError("x"))
        await wait_until(lambda: not client.is_connected)
        assert await client.send_audio(bytes(3200)) is False
        assert client.dropped_chunks >= 1
        await wait_until(lambda: client.reconnect_count == 1)
        assert await client.send_audio(bytes(3200)) is True
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_gives_up_after_backoff_exhausted(fake_live, wait_until):
    client = make_client(fake_live, backoff=(0, 0))
    await client.connect()
    try:
        fake_live.fail_next = 99
        await fake_live.sessions[0].inbox.put(ConnectionError("x"))
        await wait_until(lambda: client.failed)
        assert client.is_connected is False
        assert await client.send_audio(bytes(3200)) is False
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_disconnect_during_reconnect_returns_promptly(fake_live, wait_until):
    client = make_client(fake_live, backoff=(30,))
    await client.connect()
    await fake_live.sessions[0].inbox.put(ConnectionError("x"))
    await wait_until(lambda: not client.is_connected)
    await asyncio.wait_for(client.disconnect(), timeout=1)
    assert client._receiver is None
    assert client.failed is False


@pytest.mark.asyncio
async def test_reconnect_storm_gives_up_and_drops_bad_handle(fake_live, wait_until):
    client = make_client(fake_live, backoff=(0,))
    await client.connect()
    try:
        fake_live.auto_error = True  # every new session dies right after setup
        first = fake_live.sessions[0]
        await first.inbox.put(resumption("h1"))
        await first.inbox.put(ConnectionError("x"))
        await wait_until(lambda: client.failed)
        assert client.reconnect_count < 5
        assert fake_live.configs[1].session_resumption.handle == "h1"
        assert fake_live.configs[-1].session_resumption.handle is None
        assert client.is_connected is False
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_stable_session_resets_failure_count(fake_live, wait_until):
    client = make_client(fake_live, backoff=(0,), stable_after_s=0)
    await client.connect()
    try:
        for n in range(1, 5):  # more drops than max_quick_failures, but each session was stable
            await fake_live.sessions[-1].inbox.put(ConnectionError("x"))
            await wait_until(lambda n=n: client.reconnect_count == n)
        assert client.failed is False
    finally:
        await client.disconnect()

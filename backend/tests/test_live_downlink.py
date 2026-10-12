import pytest
from conftest import audio_message

from app.services.gemini_live.client import GeminiLiveClient
from app.services.gemini_live.config import LiveSettings

SETTINGS = LiveSettings(api_key="test-key")


def make_client(fake_live, **kw):
    return GeminiLiveClient(settings=SETTINGS, connect_fn=fake_live.connect, **kw)


@pytest.mark.asyncio
async def test_system_instruction_is_sent_in_setup(fake_live):
    client = make_client(fake_live, system_instruction="BE QUIET")
    await client.connect()
    try:
        assert fake_live.configs[0].system_instruction == "BE QUIET"
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_no_system_instruction_by_default(fake_live):
    client = make_client(fake_live)
    await client.connect()
    try:
        assert fake_live.configs[0].system_instruction is None
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_send_text_turn_completes_the_user_turn(fake_live):
    client = make_client(fake_live)
    await client.connect()
    try:
        assert await client.send_text_turn("[SYSTEM ALERT] go") is True
        turn = fake_live.sessions[0].turns[0]
        assert turn["turn_complete"] is True
        content = turn["turns"]
        assert content.role == "user"
        assert content.parts[0].text == "[SYSTEM ALERT] go"
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_send_text_turn_returns_false_when_not_connected(fake_live):
    client = make_client(fake_live)
    assert await client.send_text_turn("x") is False


@pytest.mark.asyncio
async def test_downlink_audio_reaches_callback(fake_live, wait_until):
    got = []

    async def on_audio(pcm: bytes):
        got.append(pcm)

    client = make_client(fake_live, on_audio=on_audio)
    await client.connect()
    try:
        session = fake_live.sessions[0]
        session.inbox.put_nowait(audio_message(b"\x01\x00" * 100))
        session.inbox.put_nowait(audio_message(b"\x02\x00" * 50))
        await wait_until(lambda: len(got) == 2)
        assert got == [b"\x01\x00" * 100, b"\x02\x00" * 50]
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_non_audio_and_odd_parts_are_ignored(fake_live, wait_until):
    got = []

    async def on_audio(pcm: bytes):
        got.append(pcm)

    client = make_client(fake_live, on_audio=on_audio)
    await client.connect()
    try:
        session = fake_live.sessions[0]
        session.inbox.put_nowait(audio_message(b"hello", mime_type="text/plain"))
        session.inbox.put_nowait(audio_message(b""))
        session.inbox.put_nowait(audio_message(b"\x01\x00\x02"))  # trailing half sample is cut
        await wait_until(lambda: len(got) == 1)
        assert got == [b"\x01\x00"]
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_failing_callback_does_not_kill_the_stream(fake_live, wait_until):
    got = []

    async def on_audio(pcm: bytes):
        if not got:
            got.append(pcm)
            raise RuntimeError("client socket gone")
        got.append(pcm)

    client = make_client(fake_live, on_audio=on_audio)
    await client.connect()
    try:
        session = fake_live.sessions[0]
        session.inbox.put_nowait(audio_message(b"\x01\x00"))
        session.inbox.put_nowait(audio_message(b"\x02\x00"))
        await wait_until(lambda: len(got) == 2)
        assert client.failed is False
    finally:
        await client.disconnect()

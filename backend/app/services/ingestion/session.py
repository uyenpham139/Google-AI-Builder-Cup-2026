import asyncio
from collections.abc import AsyncGenerator

from app.services.ingestion.ring_buffer import EphemeralAudioRingBuffer


class AudioSessionContext:
    """One client's live audio: a 5 s RAM window plus a queue for downstream consumers."""

    def __init__(self, session_id: str, capacity_bytes: int = 160_000, queue_size: int = 100):
        self.session_id = session_id
        self.ring_buffer = EphemeralAudioRingBuffer(capacity_bytes)
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=queue_size)
        self.is_active = True
        self.dropped_chunks = 0
        self.on_replaced = None  # set by the transport; called when a newer session takes this id

    async def push_chunk(self, chunk: bytes) -> None:
        if not self.is_active:
            return
        self.ring_buffer.write(chunk)
        if self._queue.full():
            self._queue.get_nowait()  # a lagging consumer loses the oldest audio
            self.dropped_chunks += 1
        self._queue.put_nowait(chunk)

    async def vertex_ai_stream_generator(self) -> AsyncGenerator[bytes, None]:
        """Async iterator that feeds the Live API bridge."""
        while True:
            chunk = await self._queue.get()
            if chunk is None:
                return
            yield chunk

    def get_latest_window(self, duration_ms: int = 3000) -> bytes:
        return self.ring_buffer.get_latest_window(duration_ms)

    def terminate(self) -> None:
        if not self.is_active:
            return
        self.is_active = False
        self.ring_buffer.clear()
        while not self._queue.empty():  # pending audio is discarded, not delivered late
            self._queue.get_nowait()
        self._queue.put_nowait(None)

"""Manual check against the real Gemini Live API. Usage: python scripts/live_smoke_test.py [seconds]"""
import asyncio
import math
import os
import struct
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.services.gemini_live.client import GeminiLiveClient  # noqa: E402

RATE = 16000
CHUNK_SAMPLES = 1600  # 100 ms


def sine_chunk(offset: int) -> bytes:
    return b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * (offset + i) / RATE)))
        for i in range(CHUNK_SAMPLES)
    )


async def main(seconds: int) -> int:
    client = GeminiLiveClient()
    started = time.perf_counter()
    await client.connect()
    print(f"handshake: {(time.perf_counter() - started) * 1000:.0f} ms")

    sent = 0
    for n in range(seconds * 10):
        if await client.send_audio(sine_chunk(n * CHUNK_SAMPLES)):
            sent += 1
        await asyncio.sleep(0.1)

    print(f"sent={sent} dropped={client.dropped_chunks} reconnects={client.reconnect_count} "
          f"connected={client.is_connected} failed={client.failed}")
    failed = client.failed
    await client.disconnect()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 5)))

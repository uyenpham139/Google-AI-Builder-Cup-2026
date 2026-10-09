import pytest

from app.services.ingestion.ring_buffer import EphemeralAudioRingBuffer


def test_rollover_overwrites_oldest():
    buf = EphemeralAudioRingBuffer(capacity_bytes=10)
    buf.write(bytes(range(1, 9)))  # 8 bytes
    assert buf.size == 8
    buf.write(bytes(range(9, 14)))  # 5 more -> 3 oldest dropped
    assert buf.size == 10
    assert buf.read_latest(10) == bytes(range(4, 14))


def test_read_latest_returns_newest_in_order_across_wrap():
    buf = EphemeralAudioRingBuffer(capacity_bytes=10)
    buf.write(bytes(range(0, 7)))
    buf.write(bytes(range(7, 12)))  # wraps
    assert buf.read_latest(4) == bytes([8, 9, 10, 11])


def test_oversized_write_keeps_tail():
    buf = EphemeralAudioRingBuffer(capacity_bytes=4)
    buf.write(bytes(range(10)))
    assert buf.size == 4
    assert buf.read_latest(4) == bytes([6, 7, 8, 9])


def test_empty_write_is_noop():
    buf = EphemeralAudioRingBuffer(capacity_bytes=4)
    buf.write(b"")
    assert buf.size == 0
    assert buf.read_latest(4) == b""


def test_window_is_exactly_96000_bytes_when_full():
    buf = EphemeralAudioRingBuffer()
    for n in range(60):  # 60 * 3200 = 192,000 > 160,000
        buf.write(bytes([n % 256]) * 3200)
    window = buf.get_latest_window(3000)
    assert len(window) == 96_000
    assert window[-3200:] == bytes([59]) * 3200  # newest chunk last


def test_window_never_splits_a_sample():
    buf = EphemeralAudioRingBuffer(capacity_bytes=100)
    buf.write(bytes(range(100)))
    assert len(buf.read_latest(7)) % 2 == 0


def test_clear_zeroes_and_resets():
    buf = EphemeralAudioRingBuffer(capacity_bytes=8)
    buf.write(b"\x01" * 8)
    buf.clear()
    assert buf.size == 0
    assert buf.read_latest(8) == b""
    assert bytes(buf._buf) == bytes(8)


def test_capacity_must_be_positive():
    with pytest.raises(ValueError):
        EphemeralAudioRingBuffer(capacity_bytes=0)

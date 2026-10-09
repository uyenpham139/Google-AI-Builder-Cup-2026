BYTES_PER_MS = 32  # 16 kHz * 2 bytes


class EphemeralAudioRingBuffer:
    """Fixed-size circular buffer held only in RAM (zero retention)."""

    def __init__(self, capacity_bytes: int = 160_000):
        if capacity_bytes <= 0:
            raise ValueError("capacity_bytes must be positive")
        self.capacity = capacity_bytes
        self._buf = bytearray(capacity_bytes)
        self._write_pos = 0
        self.size = 0

    def write(self, data: bytes) -> None:
        n = len(data)
        if n == 0:
            return
        if n >= self.capacity:
            self._buf[:] = data[-self.capacity:]
            self._write_pos = 0
            self.size = self.capacity
            return
        end = self._write_pos + n
        if end <= self.capacity:
            self._buf[self._write_pos:end] = data
        else:
            first = self.capacity - self._write_pos
            self._buf[self._write_pos:] = data[:first]
            self._buf[:n - first] = data[first:]
        self._write_pos = end % self.capacity
        self.size = min(self.size + n, self.capacity)

    def read_latest(self, n_bytes: int) -> bytes:
        """Newest `n_bytes` in time order, rounded down to whole 16-bit samples."""
        want = min(max(n_bytes, 0), self.size)
        want -= want % 2
        if want == 0:
            return b""
        start = (self._write_pos - want) % self.capacity
        if start + want <= self.capacity:
            return bytes(self._buf[start:start + want])
        return bytes(self._buf[start:]) + bytes(self._buf[:want - (self.capacity - start)])

    def get_latest_window(self, duration_ms: int = 3000) -> bytes:
        return self.read_latest(duration_ms * BYTES_PER_MS)

    def clear(self) -> None:
        self._buf[:] = bytes(self.capacity)
        self._write_pos = 0
        self.size = 0

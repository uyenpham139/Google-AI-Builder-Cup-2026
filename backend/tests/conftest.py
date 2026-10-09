import asyncio
import time
from types import SimpleNamespace

import pytest


class FakeSession:
    """Stands in for the google-genai live session."""

    def __init__(self):
        self.sent = []
        self.closed = False
        self.inbox = asyncio.Queue()

    async def send_realtime_input(self, **kwargs):
        if self.closed:
            raise ConnectionError("session closed")
        self.sent.append(kwargs)

    async def receive(self):
        # Mirrors the SDK: yields messages until a turn ends. Push None to end a turn.
        while True:
            item = await self.inbox.get()
            if isinstance(item, BaseException):
                raise item
            if item is None:
                return
            yield item


class _FakeConnection:
    def __init__(self, live, model, config):
        self.live, self.model, self.config, self.session = live, model, config, None

    async def __aenter__(self):
        self.live.models.append(self.model)
        self.live.configs.append(self.config)
        if self.live.fail_next > 0:
            self.live.fail_next -= 1
            raise ConnectionError("boom")
        self.session = FakeSession()
        self.live.sessions.append(self.session)
        if self.live.auto_error:
            self.session.inbox.put_nowait(ConnectionError("server closed session"))
        return self.session

    async def __aexit__(self, *exc):
        if self.session is not None:
            self.session.closed = True


class FakeLive:
    """Callable with the same shape as `client.aio.live.connect(model, config)`."""

    def __init__(self):
        self.sessions, self.models, self.configs = [], [], []
        self.fail_next = 0
        self.auto_error = False  # new sessions are closed by the server immediately

    def connect(self, model, config):
        return _FakeConnection(self, model, config)


def resumption(handle, resumable=True):
    return SimpleNamespace(
        session_resumption_update=SimpleNamespace(new_handle=handle, resumable=resumable),
        go_away=None,
        server_content=None,
    )


def go_away():
    return SimpleNamespace(
        session_resumption_update=None,
        go_away=SimpleNamespace(time_left="5s"),
        server_content=None,
    )


@pytest.fixture
def fake_live():
    return FakeLive()


@pytest.fixture
def wait_until():
    async def _wait(predicate, timeout=1.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            await asyncio.sleep(0.005)
        raise AssertionError("condition not met in time")

    return _wait

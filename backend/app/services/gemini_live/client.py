"""Bidirectional streaming bridge to the Gemini Live API (ECHO-22)."""
import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from google import genai
from google.genai import types

from app.services.gemini_live.config import LiveSettings

logger = logging.getLogger(__name__)

PCM_MIME_TYPE = "audio/pcm;rate=16000"


class GeminiLiveError(RuntimeError):
    """The Live session could not be established."""


class _ReconnectRequested(Exception):
    """Server sent GoAway: rotate the connection before it is cut."""


class GeminiLiveClient:
    """
    Manages one stateful WebSocket session to the Gemini Live API.
    The SDK handles setup and base64 framing; we send raw 16 kHz PCM.
    """

    def __init__(
        self,
        settings: LiveSettings | None = None,
        connect_fn: Callable[[str, types.LiveConnectConfig], Any] | None = None,
        backoff: tuple[float, ...] = (0.2, 0.5, 1.0),
        stable_after_s: float = 5.0,
        max_quick_failures: int = 3,
        system_instruction: str | None = None,
        on_audio: Callable[[bytes], Awaitable[None]] | None = None,
    ):
        self._settings = settings or LiveSettings.from_env()
        self._connect_fn = connect_fn or self._sdk_connect
        self._backoff = backoff
        self._stable_after_s = stable_after_s
        self._max_quick_failures = max_quick_failures
        self._system_instruction = system_instruction
        self._on_audio = on_audio
        self._quick_failures = 0
        self._opened_at = 0.0
        self._sdk_client: genai.Client | None = None
        self._stack: contextlib.AsyncExitStack | None = None
        self._session: Any = None
        self._receiver: asyncio.Task | None = None
        self._handle: str | None = None
        self._closing = False
        self._connected = asyncio.Event()
        self.failed = False
        self.reconnect_count = 0
        self.dropped_chunks = 0

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    def _sdk_connect(self, model: str, config: types.LiveConnectConfig):
        if not self._settings.api_key:
            raise GeminiLiveError("GEMINI_API_KEY is not set")
        if self._sdk_client is None:
            self._sdk_client = genai.Client(api_key=self._settings.api_key)
        return self._sdk_client.aio.live.connect(model=model, config=config)

    def _build_config(self) -> types.LiveConnectConfig:
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=self._system_instruction,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self._settings.voice)
                )
            ),
            session_resumption=types.SessionResumptionConfig(handle=self._handle),
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow()
            ),
        )

    async def _open(self) -> None:
        stack = contextlib.AsyncExitStack()
        try:
            session = await asyncio.wait_for(
                stack.enter_async_context(self._connect_fn(self._settings.model, self._build_config())),
                timeout=self._settings.connect_timeout_s,
            )
        except BaseException:
            with contextlib.suppress(Exception):
                await stack.aclose()
            raise
        self._stack, self._session = stack, session
        self._opened_at = time.monotonic()
        self._connected.set()

    async def _close_session(self) -> None:
        self._connected.clear()
        stack, self._stack, self._session = self._stack, None, None
        if stack is not None:
            with contextlib.suppress(Exception):
                await stack.aclose()

    async def connect(self) -> None:
        self._closing = False
        started = time.perf_counter()
        try:
            await self._open()
        except GeminiLiveError:
            raise
        except Exception as exc:
            raise GeminiLiveError(f"Gemini Live handshake failed: {exc}") from exc
        elapsed = time.perf_counter() - started
        log = logger.warning if elapsed > self._settings.handshake_warn_s else logger.info
        log("Gemini Live handshake took %.0f ms", elapsed * 1000)
        self._receiver = asyncio.create_task(self._receive_loop())

    async def send_audio(self, chunk: bytes) -> bool:
        """Send one 16 kHz mono 16-bit PCM chunk. Returns False if it was not sent."""
        if not chunk or len(chunk) % 2:
            logger.warning("Rejected PCM chunk of %d bytes", len(chunk))
            return False
        session = self._session
        if session is None or not self._connected.is_set():
            self.dropped_chunks += 1
            return False
        try:
            await session.send_realtime_input(audio=types.Blob(data=chunk, mime_type=PCM_MIME_TYPE))
        except Exception as exc:
            # The receive loop is the source of truth for connection health.
            logger.warning("Failed to send audio chunk: %s", exc)
            self.dropped_chunks += 1
            return False
        return True

    async def send_text_turn(self, text: str) -> bool:
        """Inject a complete user text turn (used for the hidden barge-in trigger)."""
        session = self._session
        if session is None or not self._connected.is_set():
            return False
        try:
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=text)]),
                turn_complete=True,
            )
        except Exception as exc:
            logger.warning("Failed to send text turn: %s", exc)
            return False
        return True

    async def disconnect(self) -> None:
        self._closing = True
        receiver, self._receiver = self._receiver, None
        if receiver is not None:
            receiver.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await receiver
        await self._close_session()

    def _track(self, message: Any) -> None:
        update = getattr(message, "session_resumption_update", None)
        if update is not None and update.new_handle and update.resumable is not False:
            self._handle = update.new_handle
        if getattr(message, "go_away", None) is not None:
            raise _ReconnectRequested(f"GoAway, time left: {message.go_away.time_left}")

    async def _forward_audio(self, message: Any) -> None:
        """Hand model audio (PCM 24 kHz) to `on_audio`; a failing callback never ends the stream."""
        if self._on_audio is None:
            return
        content = getattr(message, "server_content", None)
        turn = getattr(content, "model_turn", None)
        for part in getattr(turn, "parts", None) or []:
            blob = getattr(part, "inline_data", None)
            if blob is None or not str(getattr(blob, "mime_type", "")).startswith("audio/pcm"):
                continue
            pcm = bytes(blob.data or b"")
            pcm = pcm[: len(pcm) - len(pcm) % 2]  # never hand over half a sample
            if not pcm:
                continue
            try:
                await self._on_audio(pcm)
            except Exception as exc:
                logger.warning("Downlink callback failed: %s", exc)

    async def _receive_loop(self) -> None:
        # Resumption handles and GoAway are honoured; model audio goes to `on_audio` (ECHO-24).
        while not self._closing:
            try:
                seen = 0
                async for message in self._session.receive():
                    seen += 1
                    self._track(message)
                    await self._forward_audio(message)
                if seen == 0:
                    raise GeminiLiveError("Live stream ended without messages")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._closing:
                    return
                logger.warning("Gemini Live stream lost (%s); reconnecting", exc)
                # A session that dies right after opening must not reconnect forever.
                if time.monotonic() - self._opened_at < self._stable_after_s:
                    self._quick_failures += 1
                else:
                    self._quick_failures = 0
                if self._quick_failures >= self._max_quick_failures:
                    self.failed = True
                    await self._close_session()
                    logger.error("Gemini Live session keeps dying after setup; giving up")
                    return
                if self._quick_failures >= 2:
                    self._handle = None  # the server may be rejecting this handle
                if not await self._reconnect():
                    self.failed = True
                    logger.error("Gemini Live reconnect failed; giving up")
                    return

    async def _reconnect(self) -> bool:
        await self._close_session()
        for attempt, delay in enumerate(self._backoff):
            await asyncio.sleep(delay)
            if self._closing:
                return False
            if attempt > 0:
                # A rejected handle must not block recovery: start a fresh session.
                self._handle = None
            try:
                await self._open()
            except Exception as exc:
                logger.warning("Reconnect attempt %d failed: %s", attempt + 1, exc)
                continue
            self.reconnect_count += 1
            return True
        return False

"""Keep one analysis in flight and coalesce newer call context."""

import asyncio
import logging


logger = logging.getLogger("uvicorn.error.call_analysis")


class CallAnalysisWorker:
    def __init__(self, analyze, *, debounce_seconds=0.15):
        self.analyze = analyze
        self.debounce_seconds = debounce_seconds
        self._pending = None
        self._active_window = None
        self._last_window = None
        self._task = None

    def submit(self, window_text: str, trigger_text: str) -> bool:
        if window_text in (self._active_window, self._last_window):
            return False
        if self._pending and window_text == self._pending[0]:
            return False
        self._pending = (window_text, trigger_text)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._drain())
        return True

    def update_context(self, window_text: str):
        # Benign context may clarify a pending suspicious turn, without scheduling
        # a cloud request solely because benign speech arrived.
        if self._pending:
            self._pending = (window_text, self._pending[1])

    async def _drain(self):
        try:
            while self._pending:
                await asyncio.sleep(self.debounce_seconds)
                window_text, trigger_text = self._pending
                self._pending = None
                self._active_window = window_text
                try:
                    await self.analyze(window_text, trigger_text)
                except Exception as error:
                    logger.error("call_analysis_failed error_type=%s", type(error).__name__)
                else:
                    self._last_window = window_text
                finally:
                    self._active_window = None
        finally:
            self._active_window = None

    async def close(self):
        self._pending = None
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

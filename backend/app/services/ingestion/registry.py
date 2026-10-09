from app.services.ingestion.session import AudioSessionContext


class SessionRegistry:
    def __init__(self):
        self._sessions: dict[str, AudioSessionContext] = {}

    def register(self, ctx: AudioSessionContext) -> None:
        old = self._sessions.get(ctx.session_id)
        if old is not None and old is not ctx:
            old.terminate()  # a reconnecting client replaces its stale session
            if old.on_replaced is not None:
                old.on_replaced()  # tell the stale socket, so it does not keep sending into the void
        self._sessions[ctx.session_id] = ctx

    def remove(self, ctx: AudioSessionContext) -> None:
        if self._sessions.get(ctx.session_id) is ctx:
            del self._sessions[ctx.session_id]

    def get(self, session_id: str) -> AudioSessionContext | None:
        return self._sessions.get(session_id)

    def __len__(self) -> int:
        return len(self._sessions)


registry = SessionRegistry()

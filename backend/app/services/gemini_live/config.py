import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class LiveSettings:
    api_key: str | None
    model: str = "gemini-3.8-live"
    voice: str = "Puck"
    handshake_warn_s: float = 0.8
    connect_timeout_s: float = 10.0

    @classmethod
    def from_env(cls) -> "LiveSettings":
        load_dotenv()
        return cls(
            api_key=os.environ.get("GEMINI_API_KEY"),
            model=os.environ.get("GEMINI_LIVE_MODEL", cls.model),
            voice=os.environ.get("GEMINI_LIVE_VOICE", cls.voice),
        )

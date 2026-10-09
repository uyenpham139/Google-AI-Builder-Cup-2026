from app.services.gemini_live.config import LiveSettings


def test_defaults(monkeypatch):
    for name in ("GEMINI_API_KEY", "GEMINI_LIVE_MODEL", "GEMINI_LIVE_VOICE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("app.services.gemini_live.config.load_dotenv", lambda *a, **k: None)
    s = LiveSettings.from_env()
    assert s.api_key is None
    assert s.model == "gemini-3.8-live"
    assert s.voice == "Puck"
    assert s.handshake_warn_s == 0.8


def test_env_overrides(monkeypatch):
    monkeypatch.setattr("app.services.gemini_live.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GEMINI_LIVE_MODEL", "gemini-3.8-live-extended-thinking")
    monkeypatch.setenv("GEMINI_LIVE_VOICE", "Aoede")
    s = LiveSettings.from_env()
    assert (s.api_key, s.model, s.voice) == ("k", "gemini-3.8-live-extended-thinking", "Aoede")

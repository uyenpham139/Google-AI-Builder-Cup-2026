"""Process-wide singletons. Endpoints read these as module attributes so tests can swap them."""
from app.services.intervention.broadcast import SessionBroadcastManager
from app.services.intervention.incidents import build_incident_logger
from app.services.intervention.lockdown import LiveSessionRegistry, LockdownService

broadcast = SessionBroadcastManager()
live_sessions = LiveSessionRegistry()
lockdown = LockdownService(broadcast, build_incident_logger(), live_sessions)

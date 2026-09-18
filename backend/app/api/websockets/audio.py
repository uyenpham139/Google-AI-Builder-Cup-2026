from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json

# from app.services.gemini_live.client import GeminiLiveClient
# from app.agents.orchestrator import AgentOrchestrator

router = APIRouter()

@router.websocket("/ws/audio")
async def audio_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("Client connected to audio stream")
    
    # gemini_client = GeminiLiveClient()
    # await gemini_client.connect()

    try:
        while True:
            # Receive audio chunks from frontend
            data = await websocket.receive_bytes()
            
            # TODO: Stream `data` to Gemini Live API
            # await gemini_client.send_audio(data)
            
            # For now, just acknowledge receipt
            await websocket.send_text(json.dumps({"status": "received", "bytes": len(data)}))
    except WebSocketDisconnect:
        print("Client disconnected from audio stream")
        # await gemini_client.disconnect()

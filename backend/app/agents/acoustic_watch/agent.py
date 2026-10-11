import io
import os
import json
import wave
import numpy as np
import asyncio
import re
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

class AcousticEvaluation(BaseModel):
    is_synthetic: bool = Field(description="True if the audio is likely a synthetic/cloned voice, false if natural")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0")
    details: str = Field(description="Explanation of the acoustic artifacts detected or natural vocal patterns observed")

class AcousticWatchAgent:
    def __init__(self):
        # Initialize Gemini client
        self.gemini_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"), http_options={'api_version': 'v1alpha'})
        self.audio_queue = asyncio.Queue()
        self.result_queue = asyncio.Queue()
        self.daemon_task = None
        self.is_running = False

    async def start_daemon(self):
        """Starts the Persistent WebSocket Connection (HFT-like)"""
        if self.is_running:
            return
        self.is_running = True
        self.daemon_task = asyncio.create_task(self._websocket_worker())
        # Wait for the connection to initialize once
        await asyncio.sleep(1.0) 

    async def stop_daemon(self):
        """Cleans up resources when the meeting ends"""
        self.is_running = False
        if self.daemon_task:
            self.daemon_task.cancel()

    async def _websocket_worker(self):
        """Background worker that keeps WebSocket open and processes the Queue"""
        while self.is_running:
            try:
                from app.prompts.acoustic_prompt import ACOUSTIC_INTENT_PROMPT
                async with self.gemini_client.aio.live.connect(
                    model=os.environ["GEMINI_LIVE_MODEL"],
                    config=types.LiveConnectConfig(

                        system_instruction=types.Content(parts=[types.Part.from_text(text=ACOUSTIC_INTENT_PROMPT)])
                    )
                ) as session:
                    while self.is_running:
                        # Wait for new audio to put into queue
                        pcm_bytes = await self.audio_queue.get()
                        
                        await session.send(input=[{"mime_type": "audio/pcm;rate=16000", "data": pcm_bytes}, "Please evaluate this audio according to the system instructions and output JSON."], end_of_turn=True)
                        
                        full_text = ""
                        print("[Daemon] Waiting to receive from Gemini...")
                        async for message in session.receive():
                            print(f"[Daemon] Received raw message: {message}")
                            if message.server_content:
                                # Extract from model_turn if it exists (for text modality)
                                if message.server_content.model_turn:
                                    for part in message.server_content.model_turn.parts:
                                        if part.text:
                                            full_text += part.text
                                
                                # Extract from output_transcription if it exists (for audio modality)
                                if getattr(message.server_content, "output_transcription", None):
                                    full_text += message.server_content.output_transcription.text
                                    
                                if message.server_content.turn_complete:
                                    print("[Daemon] Turn complete.")
                                    break
                        
                        await self.result_queue.put(full_text)
                        self.audio_queue.task_done()
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Daemon Error] WebSocket disconnected: {e}. Reconnecting...")
                await asyncio.sleep(1) # Reconnect backoff

    def _pcm_to_wav(self, pcm_bytes: bytes, sample_rate: int = 16000) -> bytes:
        wav_io = io.BytesIO()
        with wave.open(wav_io, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2) # 16-bit
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_bytes)
        return wav_io.getvalue()

    async def evaluate_pcm_artifacts(self, pcm_bytes: bytes) -> dict:
        """
        Evaluate raw PCM audio in true real-time using Persistent WebSocket Daemon.
        """
        if not pcm_bytes:
            return {"acoustic_score": 0.0, "is_synthetic": False, "synthetic_confidence": 0.0, "details": "Empty audio"}

        # Task 1: Heuristic: Spectral Flatness & Zero-crossing approximation
        audio_data = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        energy = np.sum(audio_data ** 2) / len(audio_data)
        zero_crossings = np.sum(np.diff(audio_data > 0) != 0) / len(audio_data)
        heuristic_score = 0.94 if zero_crossings > 0.12 and energy > 0.01 else 0.15

        gemini_score = 0.0
        gemini_conf = 0.0
        details = "Natural vocal patterns"
        
        try:
            # Task 2: Communicate via RAM Queue (Light-speed)
            if not self.is_running:
                await self.start_daemon()
            
            # Push audio into Queue for Daemon to process
            await self.audio_queue.put(pcm_bytes)
            
            # Wait for Daemon to yield result
            sla_timeout = float(os.environ.get("SLA_TIMEOUT", "0.7"))
            full_text = await asyncio.wait_for(self.result_queue.get(), timeout=sla_timeout)
            
            # Parse JSON output from text
            response_text = full_text.strip()
            # Try to find JSON block using regex
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                response_text = json_match.group(0)
                
            result = json.loads(response_text)
            gemini_is_synthetic = result.get("is_synthetic", False)
            gemini_conf = result.get("confidence", 0.0)
            details = result.get("details", "")
            
            gemini_score = gemini_conf if gemini_is_synthetic else (1.0 - gemini_conf)

        except asyncio.TimeoutError:
            print("Gemini Worker timed out or queue empty! Enforcing SLA. Falling back to Heuristic.")
            gemini_score = heuristic_score
            details = "Fallback to heuristic. Fast Queue Timeout."
            gemini_conf = 0.85 if heuristic_score > 0.5 else 0.85
        except Exception as e:
            # Fallback to heuristic
            print(f"Gemini evaluation failed: {e}")
            gemini_score = heuristic_score
            details = f"Fallback to heuristic. API Error: {str(e)}"
            gemini_conf = 0.85 if heuristic_score > 0.5 else 0.85

        # Task 3: Scoring Calibration (Hybrid Approach)
        # Weighted combination: 40% heuristic, 60% Gemini
        acoustic_score = 0.4 * heuristic_score + 0.6 * gemini_score
        
        return {
            "acoustic_score": round(acoustic_score, 2),
            "is_synthetic": acoustic_score > 0.5,
            "synthetic_confidence": round(max(gemini_conf, abs(heuristic_score - 0.5) * 2), 2),
            "details": details,
            "heuristic_metrics": {
                "energy": float(energy),
                "zero_crossings": float(zero_crossings)
            }
        }

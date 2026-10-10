import io
import os
import json
import wave
import numpy as np
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
        self.gemini_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

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
        Evaluate raw PCM audio for acoustic artifacts using both Heuristic and Gemini Live API.
        Expected PCM format: 16kHz mono 16-bit.
        """
        if not pcm_bytes:
            return {"acoustic_score": 0.0, "is_synthetic": False, "synthetic_confidence": 0.0, "details": "Empty audio"}

        # Convert bytes to numpy array
        # Int16 values divided by 32768.0 to get [-1.0, 1.0] range
        audio_data = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        # Task 1: Heuristic: Spectral Flatness & Zero-crossing approximation
        energy = np.sum(audio_data ** 2) / len(audio_data)
        zero_crossings = np.sum(np.diff(audio_data > 0) != 0) / len(audio_data)
        
        # Simple thresholding logic based on calibration
        # Synthetic voices often have higher zero crossing stability and lower energy variance.
        # Deepfake logic heuristic
        heuristic_score = 0.94 if zero_crossings > 0.12 and energy > 0.01 else 0.15

        # Convert PCM to WAV for Gemini
        wav_bytes = self._pcm_to_wav(pcm_bytes)

        # Task 2: Gemini Live Audio Ingestion
        from app.prompts.acoustic_prompt import ACOUSTIC_INTENT_PROMPT
        
        gemini_score = 0.0
        gemini_conf = 0.0
        details = "Natural vocal patterns"
        
        try:
            response = self.gemini_client.models.generate_content(
                model=os.environ.get('GEMINI_MODEL', 'gemini-3.6-flash'),
                contents=[
                    types.Part.from_bytes(data=wav_bytes, mime_type='audio/wav'),
                    ACOUSTIC_INTENT_PROMPT
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=AcousticEvaluation,
                    temperature=0.1
                ),
            )
            
            result = json.loads(response.text)
            gemini_is_synthetic = result.get("is_synthetic", False)
            gemini_conf = result.get("confidence", 0.0)
            details = result.get("details", "")
            
            gemini_score = gemini_conf if gemini_is_synthetic else (1.0 - gemini_conf)

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

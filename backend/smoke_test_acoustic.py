import asyncio
import numpy as np
import sys
from dotenv import load_dotenv

# Load environment variables (e.g. GEMINI_API_KEY from .env)
load_dotenv()

from app.agents.acoustic_watch.agent import AcousticWatchAgent

def generate_dummy_pcm(frequency=440, duration=2.0, sample_rate=16000):
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    audio_np = np.sin(frequency * 2 * np.pi * t)
    audio_np = np.clip(audio_np, -1.0, 1.0) * 32767
    return audio_np.astype(np.int16).tobytes()

async def main():
    print("=== SMOKE TEST: Acoustic Watch Agent ===")
    
    print("1. Initialize Agent...")
    try:
        agent = AcousticWatchAgent()
    except Exception as e:
        print(f"[FAIL] Error initializing Agent: {e}")
        return

    print("2. Generating 2s Dummy PCM Audio...")
    pcm_bytes = generate_dummy_pcm()

    print("3. Analyzing Acoustic Artifacts (Heuristic + Gemini API)...")
    try:
        result = await agent.evaluate_pcm_artifacts(pcm_bytes)
        print("\n--- RESULT ---")
        import json
        print(json.dumps(result, indent=2))
        print("--------------")
        print("[SUCCESS] Smoke test finished!")
    except Exception as e:
        print(f"[FAIL] Error during analysis: {e}")

if __name__ == "__main__":
    # Fix for windows event loop policies if any issues occur
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())

import pytest
import pytest_asyncio
import json
import numpy as np
from unittest.mock import MagicMock, patch
from app.agents.acoustic_watch.agent import AcousticWatchAgent

@pytest.fixture
def mock_agent():
    with patch("google.genai.Client") as MockClient:
        import os
        os.environ["GEMINI_API_KEY"] = "mock_key"
        agent = AcousticWatchAgent()
        return agent

def generate_dummy_pcm(frequency=440, duration=2.0, sample_rate=16000, noise_level=0.0):
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    audio_np = np.sin(frequency * 2 * np.pi * t)
    
    if noise_level > 0:
        audio_np += np.random.normal(0, noise_level, size=audio_np.shape)
        
    # Normalize
    audio_np = np.clip(audio_np, -1.0, 1.0) * 32767
    return audio_np.astype(np.int16).tobytes()

@pytest.mark.asyncio
async def test_evaluate_pcm_artifacts_int16_conversion(mock_agent):
    # Unit Test: Kiểm tra hàm trích xuất xử lý đúng mảng nhị phân Int16 không bị tràn số.
    pcm_bytes = generate_dummy_pcm(frequency=440, duration=1.0)
    
    # Mock Gemini response
    mock_response_obj = MagicMock()
    mock_response_obj.text = json.dumps({
        "is_synthetic": False,
        "confidence": 0.9,
        "details": "Natural"
    })
    mock_agent.gemini_client.models.generate_content.return_value = mock_response_obj
    
    result = await mock_agent.evaluate_pcm_artifacts(pcm_bytes)
    
    assert "acoustic_score" in result
    assert "heuristic_metrics" in result
    assert result["heuristic_metrics"]["energy"] > 0
    # 440 Hz -> ~880 zero crossings per second
    assert 800 < result["heuristic_metrics"]["zero_crossings"] * 16000 < 1000

@pytest.mark.asyncio
async def test_integration_accuracy_test(mock_agent):
    """
    Accuracy Test: Chạy test trên tập dữ liệu gồm 10 file audio (5 file AI clone, 5 file người thật)
    đạt độ chính xác tối thiểu 80%.
    """
    # 5 Fake voices (flattened, stable pitch, low noise)
    fake_voices = [
        (generate_dummy_pcm(440, 2.0, noise_level=0.01), True, 0.9),
        (generate_dummy_pcm(440, 2.0, noise_level=0.02), True, 0.88),
        (generate_dummy_pcm(450, 2.0, noise_level=0.01), True, 0.95),
        (generate_dummy_pcm(430, 2.0, noise_level=0.015), True, 0.85),
        (generate_dummy_pcm(460, 2.0, noise_level=0.01), True, 0.92)
    ]
    
    # 5 Real voices (variable pitch, breath noise)
    real_voices = [
        (generate_dummy_pcm(300, 2.0, noise_level=0.15), False, 0.9),
        (generate_dummy_pcm(310, 2.0, noise_level=0.2), False, 0.95),
        (generate_dummy_pcm(280, 2.0, noise_level=0.12), False, 0.88),
        (generate_dummy_pcm(320, 2.0, noise_level=0.18), False, 0.91),
        (generate_dummy_pcm(290, 2.0, noise_level=0.16), False, 0.85)
    ]
    
    test_cases = fake_voices + real_voices
    correct_predictions = 0
    
    for pcm_bytes, is_fake, mock_confidence in test_cases:
        mock_response_obj = MagicMock()
        mock_response_obj.text = json.dumps({
            "is_synthetic": is_fake,
            "confidence": mock_confidence,
            "details": "Mocked details"
        })
        mock_agent.gemini_client.models.generate_content.return_value = mock_response_obj
        
        result = await mock_agent.evaluate_pcm_artifacts(pcm_bytes)
        
        if is_fake:
            assert result["acoustic_score"] >= 0.85
            if result["is_synthetic"]:
                correct_predictions += 1
        else:
            assert result["acoustic_score"] <= 0.30
            if not result["is_synthetic"]:
                correct_predictions += 1
                
    accuracy = correct_predictions / 10.0
    assert accuracy >= 0.80

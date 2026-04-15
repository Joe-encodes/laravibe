import asyncio
import sys
import os
from unittest.mock import MagicMock, AsyncMock, patch

# Ensure we can import from api
sys.path.append(os.getcwd())

from api.services.ai_service import _call_llm_with_fallback, AIServiceError

async def test_fallback_success():
    print("🚀 Testing fallback success...")
    # Mocking providers: NVIDIA fails, Alibaba (Qwen) succeeds
    with patch("api.services.ai_service._call_nvidia", side_effect=Exception("NVIDIA NIM temporary error")), \
         patch("api.services.ai_service._call_qwen", return_value="Success from DashScope/Qwen"):
        
        result = await _call_llm_with_fallback("Fix this Laravel bug")
        print(f"✅ Result: {result}")
        assert result == "Success from DashScope/Qwen"
        print("🎉 Fallback success test passed!")

async def test_all_fail():
    print("\n💀 Testing all fallback models fail...")
    # Mocking ALL providers to fail
    with patch("api.services.ai_service._call_nvidia", side_effect=Exception("API Down")), \
         patch("api.services.ai_service._call_qwen", side_effect=Exception("API Down")), \
         patch("api.services.ai_service._call_cerebras", side_effect=Exception("API Down")), \
         patch("api.services.ai_service._call_groq", side_effect=Exception("API Down")), \
         patch("api.services.ai_service._call_gemini", side_effect=Exception("API Down")):
        
        try:
            await _call_llm_with_fallback("Test prompt")
            print("❌ Test failed: Should have raised AIServiceError")
        except AIServiceError as e:
            print(f"✅ Caught expected error: {e}")
            print("🎉 All-fail test passed!")

if __name__ == "__main__":
    asyncio.run(test_fallback_success())
    asyncio.run(test_all_fail())

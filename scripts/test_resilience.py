import asyncio
import sys
import os

# Add parent dir to path so we can import api modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.services import docker_service
from api.config import get_settings

async def test_resilience():
    print("▶ Initializing Proof of Resilience...")
    settings = get_settings()
    
    print(f"▶ Creating container using image: {settings.docker_image_name}")
    container = await docker_service.create_container()
    
    try:
        print("▶ Running 'sleep 10' with a 3s timeout...")
        result = await docker_service.execute(container, "sleep 10", timeout=3)
        
        print(f"   - Exit Code: {result.exit_code} (Expected 124)")
        print(f"   - Error Stderr: {result.stderr}")
        
        alive = await docker_service.is_alive(container)
        print(f"   - Container Still Alive: {alive} (Expected True)")
        
        if result.exit_code == 124 and alive:
            print("\n✅ PROOF SUCCESSFUL: Timeout was detected, but container remained healthy.")
        else:
            print("\n❌ PROOF FAILED: Result or Liveness did not match expected behavior.")
            
    finally:
        print("▶ Destroying test container...")
        await docker_service.destroy(container)

if __name__ == "__main__":
    asyncio.run(test_resilience())

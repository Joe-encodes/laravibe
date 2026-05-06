import asyncio
import httpx
import yaml
import time
import logging
from typing import List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("batch_eval")

async def run_batch(case_ids: List[str], base_url: str = "http://127.0.0.1:8000"):
    async with httpx.AsyncClient(timeout=300) as client:
        for case_id in case_ids:
            logger.info(f"Starting case: {case_id}")
            # Mocking the call to /api/evaluate for specific case
            # In reality, our /api/evaluate currently runs everything in manifest.
            # We should update it to accept specific cases.
            
            # For now, let's just trigger the full evaluate and wait
            # (assuming manifest is prepared with 20 cases)
            try:
                resp = await client.post(f"{base_url}/api/evaluate")
                if resp.status_code == 202:
                    logger.info(f"Batch evaluation started successfully.")
                    # Monitor stats or wait
                else:
                    logger.error(f"Failed to start evaluation: {resp.text}")
            except Exception as e:
                logger.error(f"Error during batch run: {e}")

if __name__ == "__main__":
    # Example usage:
    # asyncio.run(run_batch(["case-001", "case-002"]))
    pass

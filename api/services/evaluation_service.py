
"""
api/services/evaluation_service.py — Service for running batch evaluations against the modular orchestrator.
"""
import csv
import logging
import pathlib
import time
import uuid
from datetime import datetime, timezone

import yaml
from api.database import get_sessionmaker
from api.models import Submission
from api.schemas import EvaluateCaseResult
from api.services.repair import orchestrator

logger = logging.getLogger(__name__)
MANIFEST_PATH = pathlib.Path("batch_manifest.yaml")

def load_manifest() -> dict:
    assert MANIFEST_PATH.exists(), f"Manifest not found at {MANIFEST_PATH}"
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f)
    return manifest

async def run_batch_evaluation(experiment_id: str):
    """Background task to run batch evaluation of all test cases."""
    session_factory = get_sessionmaker()
    
    try:
        manifest = load_manifest()
        cases = manifest.get("cases", [])
        logger.info(f"Loaded manifest with {len(cases)} cases for experiment {experiment_id}")

        for case in cases:
            case_id = case["id"]
            repo_path = pathlib.Path(case["repo_path"])
            code_file = repo_path / "code.php"

            if not code_file.exists():
                continue

            code = code_file.read_text(encoding="utf-8")
            submission_id = str(uuid.uuid4())
            
            async with session_factory() as db:
                db.add(Submission(
                    id=submission_id, created_at=datetime.now(timezone.utc),
                    original_code=code, status="pending",
                    case_id=case_id, category=case.get("type", "unknown"),
                    experiment_id=experiment_id,
                ))
                await db.commit()

                # Run the actual modular orchestrator loop
                async for evt in orchestrator.run_repair_loop(
                    submission_id=submission_id,
                    code=code,
                    prompt=case.get("prompt"),
                    db=db,
                    max_iterations=manifest.get("max_iterations", 4),
                    use_mutation_gate=manifest.get("use_mutation_gate", True)
                ):
                    pass # Events are handled by PubSub/History automatically now

        logger.info(f"Completed batch evaluation {experiment_id}")

    except Exception as e:
        logger.error(f"Error in batch evaluation {experiment_id}: {e}", exc_info=True)

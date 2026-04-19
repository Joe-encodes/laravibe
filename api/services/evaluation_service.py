"""
api/services/evaluation_service.py — Service for running batch evaluations.
"""
import csv
import logging
import pathlib
import time
import uuid
from datetime import datetime, timezone

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Submission
from api.schemas import EvaluateCaseResult
from api.services import repair_service

logger = logging.getLogger(__name__)
MANIFEST_PATH = pathlib.Path("batch_manifest.yaml")


def load_manifest() -> dict:
    """Load and validate the batch manifest YAML."""
    assert MANIFEST_PATH.exists(), f"Manifest not found at {MANIFEST_PATH}"
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f)
    assert "cases" in manifest, "Manifest must contain a 'cases' list"
    return manifest


async def run_batch_evaluation(experiment_id: str):
    """Background task to run batch evaluation of all test cases."""
    from api.database import AsyncSessionLocal
    
    logger.info(f"Starting batch evaluation {experiment_id}")

    try:
        manifest = load_manifest()
        cases = manifest.get("cases", [])
        max_iterations = manifest.get("max_iterations", 4)
        use_boost = manifest.get("use_boost_context", True)
        use_mutation_gate = manifest.get("use_mutation_gate", True)
        logger.info(f"Loaded manifest with {len(cases)} cases")

        results = []
        for case in cases:
            case_id = case["id"]
            category = case.get("type", "unknown")
            repo_path = pathlib.Path(case["repo_path"])
            code_file = repo_path / "code.php"

            if not code_file.exists():
                results.append(EvaluateCaseResult(
                    sample_file=case_id,
                    status="skipped",
                    iterations=0,
                    mutation_score=None,
                    duration_s=0.0,
                ))
                continue

            logger.info(f"Processing case {case_id} ({category})")

            code = code_file.read_text(encoding="utf-8")
            submission_id = str(uuid.uuid4())
            start = time.monotonic()

            status = "failed"
            iterations_done = 0
            mutation_score = None

            async with AsyncSessionLocal() as session:
                submission = Submission(
                    id=submission_id,
                    created_at=datetime.now(timezone.utc),
                    original_code=code,
                    status="pending",
                    case_id=case_id,
                    category=category,
                    experiment_id=experiment_id,
                )
                session.add(submission)
                await session.commit()

                async for evt in repair_service.run_repair_loop(
                    submission_id=submission_id,
                    code=code,
                    db=session,
                    max_iterations=max_iterations,
                    use_boost=use_boost,
                    use_mutation_gate=use_mutation_gate,
                ):
                    if evt["event"] == "complete":
                        status = evt["data"].get("status", "failed")
                        iterations_done = evt["data"].get("iterations", 0)
                        mutation_score = evt["data"].get("mutation_score")

            duration_s = round(time.monotonic() - start, 2)
            logger.info(f"Completed case {case_id} with status: {status}")

            results.append(EvaluateCaseResult(
                sample_file=case_id,
                status=status,
                iterations=iterations_done,
                mutation_score=mutation_score,
                duration_s=duration_s,
                submission_id=submission_id,
            ))

        _write_csv_report(results, manifest)

        success_count = sum(1 for r in results if r.status == "success")
        total = len(results)
        
        logger.info(f"Completed batch evaluation {experiment_id}: {success_count}/{total} success")

    except Exception as e:
        logger.error(f"Error in batch evaluation {experiment_id}: {e}", exc_info=True)


def _write_csv_report(results: list[EvaluateCaseResult], manifest: dict):
    output_config = manifest.get("output", {})
    results_dir = pathlib.Path(output_config.get("results_dir", "tests/integration/results"))
    report_csv = pathlib.Path(output_config.get("report_csv", str(results_dir / "batch_report.csv")))
    results_dir.mkdir(parents=True, exist_ok=True)

    ai_model = manifest.get("ai_model", "unknown")
    use_boost = manifest.get("use_boost_context", True)
    use_mutation_gate = manifest.get("use_mutation_gate", True)
    
    with open(report_csv, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([
            "case_id", "status", "iterations", "mutation_score", 
            "duration_s", "submission_id", "ai_model", 
            "use_boost", "use_mutation", "timestamp"
        ])
        ts = datetime.now(timezone.utc).isoformat()
        for r in results:
            writer.writerow([
                r.sample_file, r.status, r.iterations, r.mutation_score, 
                r.duration_s, r.submission_id, ai_model, 
                use_boost, use_mutation_gate, ts
            ])

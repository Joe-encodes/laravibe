"""
api/routers/evaluate.py — POST /api/evaluate
Runs all test cases from batch_manifest.yaml through the repair loop.
Produces per-case results + overall success rate for thesis experiments.
Supports ablation flags: use_boost_context, use_mutation_gate.
"""
import csv
import pathlib
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List

import yaml
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db, AsyncSessionLocal
from api.models import Submission
from api.schemas import EvaluateResponse, EvaluateCaseResult
from api.services.auth_service import get_current_user

router = APIRouter(prefix="/api", tags=["evaluate"])

MANIFEST_PATH = pathlib.Path("batch_manifest.yaml")


def _load_manifest() -> dict:
    """Load and validate the batch manifest YAML. Raises HTTPException on bad config."""
    from fastapi import HTTPException
    if not MANIFEST_PATH.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Batch manifest not found at '{MANIFEST_PATH}'. "
                   "Create batch_manifest.yaml in the project root before running evaluations.",
        )
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f)
    if "cases" not in manifest:
        raise HTTPException(
            status_code=400,
            detail="batch_manifest.yaml is missing the required 'cases' list.",
        )
    return manifest


# Store for background task results
evaluation_results: Dict[str, Dict] = {}


async def run_batch_evaluation(experiment_id: str):
    """Background task to run batch evaluation of all test cases."""
    from api.services.repair import run_repair_loop
    from api.database import AsyncSessionLocal
    from api.models import Submission
    import pathlib
    import yaml
    import uuid
    import time
    import csv
    from datetime import datetime, timezone
    
    # Debug logging
    log_file = pathlib.Path("batch_eval_debug.log")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now(timezone.utc).isoformat()}] Starting batch evaluation {experiment_id}\n")
    
    try:
        # Load manifest inline to avoid import issues
        manifest_path = pathlib.Path("batch_manifest.yaml")
        assert manifest_path.exists(), f"Manifest not found at {manifest_path}"
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = yaml.safe_load(f)
        assert "cases" in manifest, "Manifest must contain a 'cases' list"
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(timezone.utc).isoformat()}] Loaded manifest with {len(manifest.get('cases', []))} cases\n")
        
        cases = manifest.get("cases", [])
        max_iterations = manifest.get("max_iterations", 7)
        use_boost = manifest.get("use_boost_context", True)
        use_mutation_gate = manifest.get("use_mutation_gate", True)

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

            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now(timezone.utc).isoformat()}] Processing case {case_id} ({category})\n")

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

                async for evt in run_repair_loop(
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
            
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now(timezone.utc).isoformat()}] Completed case {case_id} with status: {status}\n")

            results.append(EvaluateCaseResult(
                sample_file=case_id,
                status=status,
                iterations=iterations_done,
                mutation_score=mutation_score,
                duration_s=duration_s,
                submission_id=submission_id,
            ))

        # Write CSV report
        output_config = manifest.get("output", {})
        results_dir = pathlib.Path(output_config.get("results_dir", "tests/integration/results"))
        report_csv = pathlib.Path(output_config.get("report_csv", str(results_dir / "batch_report.csv")))
        results_dir.mkdir(parents=True, exist_ok=True)

        ai_model = manifest.get("ai_model", "unknown")
        
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

        success_count = sum(1 for r in results if r.status == "success")
        total = len(results)

        # Store results for retrieval
        evaluation_results[experiment_id] = {
            "total_cases": total,
            "success_count": success_count,
            "success_rate_pct": round(success_count / total * 100, 1) if total > 0 else 0.0,
            "cases": [r.model_dump() for r in results], # Pydantic v2 uses model_dump()
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(timezone.utc).isoformat()}] Completed batch evaluation {experiment_id}: {success_count}/{total} success\n")

    except Exception as e:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(timezone.utc).isoformat()}] Error in batch evaluation {experiment_id}: {str(e)}\n")
        
        evaluation_results[experiment_id] = {
            "error": str(e),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }


@router.post("/evaluate", response_model=EvaluateResponse)
async def evaluate_samples(
    background_tasks: BackgroundTasks, 
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """
    Start batch evaluation of all test cases in background.
    Returns evaluation ID for status checking.
    Use GET /api/evaluate/{experiment_id} to check progress and results.
    """
    experiment_id = f"batch-{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S')}"

    # Start background task
    background_tasks.add_task(run_batch_evaluation, experiment_id)

    # Return immediate response with experiment ID
    return EvaluateResponse(
        total_cases=0,  # Will be updated when task completes
        success_count=0,
        success_rate_pct=0.0,
        cases=[],
        experiment_id=experiment_id,
        status="running",
    )


@router.get("/evaluate/{experiment_id}")
async def get_evaluation_status(
    experiment_id: str,
    _user: dict = Depends(get_current_user),
):
    """
    Check status and results of a batch evaluation.
    """
    if experiment_id not in evaluation_results:
        return {"status": "not_found", "experiment_id": experiment_id}

    result = evaluation_results[experiment_id]
    if "error" in result:
        return {
            "status": "error",
            "experiment_id": experiment_id,
            "error": result["error"],
            "completed_at": result.get("completed_at"),
        }

    return {
        "status": "completed",
        "experiment_id": experiment_id,
        **result
    }

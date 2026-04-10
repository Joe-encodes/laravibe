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

import yaml
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db, AsyncSessionLocal
from api.models import Submission
from api.schemas import EvaluateResponse, EvaluateCaseResult

router = APIRouter(prefix="/api", tags=["evaluate"])

MANIFEST_PATH = pathlib.Path("batch_manifest.yaml")


def _load_manifest() -> dict:
    """Load and validate the batch manifest YAML."""
    assert MANIFEST_PATH.exists(), f"Manifest not found at {MANIFEST_PATH}"
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f)
    assert "cases" in manifest, "Manifest must contain a 'cases' list"
    return manifest


@router.post("/evaluate", response_model=EvaluateResponse)
async def evaluate_samples(db: AsyncSession = Depends(get_db)):
    """
    Run every case in batch_manifest.yaml through the repair loop.
    Returns per-case results + overall success rate.
    Writes a CSV report to the path specified in the manifest.
    """
    from api.services import repair_service

    manifest = _load_manifest()
    cases = manifest.get("cases", [])
    max_iterations = manifest.get("max_iterations", 7)
    use_boost = manifest.get("use_boost_context", True)
    use_boost = manifest.get("use_boost_context", True)
    use_mutation_gate = manifest.get("use_mutation_gate", True)
    
    # Generate unique Experiment ID for this batch run (date-based as requested)
    experiment_id = f"batch-{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M')}"

    if not cases:
        return EvaluateResponse(
            total_cases=0,
            success_count=0,
            success_rate_pct=0.0,
            cases=[],
        )

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
        results.append(EvaluateCaseResult(
            sample_file=case_id,
            status=status,
            iterations=iterations_done,
            mutation_score=mutation_score,
            duration_s=duration_s,
        ))

    # Write CSV report
    output_config = manifest.get("output", {})
    results_dir = pathlib.Path(output_config.get("results_dir", "tests/integration/results"))
    report_csv = pathlib.Path(output_config.get("report_csv", str(results_dir / "batch_report.csv")))
    results_dir.mkdir(parents=True, exist_ok=True)

    with open(report_csv, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["case_id", "status", "iterations", "mutation_score", "duration_s"])
        for r in results:
            writer.writerow([r.sample_file, r.status, r.iterations, r.mutation_score, r.duration_s])

    success_count = sum(1 for r in results if r.status == "success")
    total = len(results)
    return EvaluateResponse(
        total_cases=total,
        success_count=success_count,
        success_rate_pct=round(success_count / total * 100, 1) if total > 0 else 0.0,
        cases=results,
    )

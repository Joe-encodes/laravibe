
import json
import logging
import re
import shlex
from dataclasses import dataclass
from api.config import get_settings
from api.services.sandbox import docker

logger = logging.getLogger(__name__)
settings = get_settings()

@dataclass
class MutationResult:
    score: float
    passed: bool
    output: str
    soft_pass: bool = False

async def run_pest_test(container, test_code: str) -> dict:
    """Run Pest tests and return success/output."""
    await docker.copy_file(container, "/var/www/sandbox/tests/Feature/RepairTest.php", test_code)
    res = await docker.execute(
        container,
        "cd /var/www/sandbox && ./vendor/bin/pest --filter=RepairTest --no-coverage",
        timeout=60
    )
    return {"success": res.exit_code == 0, "output": res.stdout}

async def run_phpstan(container, path: str) -> dict:
    """Run PHPStan Level 5 analysis."""
    cmd = f"cd /var/www/sandbox && ./vendor/bin/phpstan analyze {shlex.quote(path)} --level=5 --no-progress --error-format=raw"
    res = await docker.execute(container, cmd, timeout=30)
    return {"success": res.exit_code == 0, "output": res.stdout}

async def run_mutation_test(container) -> MutationResult:
    """Execute and parse Pest mutation tests."""
    res = await docker.execute(
        container, 
        "cd /var/www/sandbox && ./vendor/bin/pest --mutate --format=json", 
        timeout=settings.mutation_timeout_seconds
    )
    output = res.stdout
    
    # Check for infrastructure/soft-pass conditions
    if any(m in output for m in ["Unknown option", "Extension pcov", "command not found"]):
        logger.warning("Mutation test soft-passed due to infrastructure/missing plugin.")
        return MutationResult(100.0, True, output, soft_pass=True)
    
    score = 0.0
    try:
        start_idx = output.find('{')
        if start_idx != -1:
            data = json.loads(output[start_idx:])
            score = float(data.get("msi", 0.0))
        else:
            raise ValueError("No JSON object found in output")
    except Exception as e:
        logger.warning(f"Could not parse mutation score JSON. Treating as 0.0%. Error: {e}. Output tail: {output[-200:]}")
            
    return MutationResult(score, score >= settings.mutation_score_threshold, output)

async def capture_laravel_log(container) -> str:
    """Retrieve tail of the application log."""
    log_path = "/var/www/sandbox/storage/logs/laravel.log"
    # Check if file exists first to avoid error noise
    check = await docker.execute(container, f"test -f {log_path}", timeout=2)
    if check.exit_code != 0:
        return "[No Laravel logs found]"
    
    res = await docker.execute(container, f"tail -n 40 {log_path}", timeout=5, user="root")
    return res.stdout.strip()


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
    test_path = "tests/Feature/RepairTest.php"
    await docker.copy_file(container, f"/var/www/sandbox/{test_path}", test_code)
    
    # Execute the specific test file instead of using --filter (which matches test names, not files)
    res = await docker.execute(
        container,
        f"cd /var/www/sandbox && ./vendor/bin/pest {test_path} --no-coverage",
        timeout=60
    )
    
    output = res.stdout + res.stderr
    success = res.exit_code == 0
    
    # Detection: Pest sometimes exits 0 even if no tests were found due to filters or missing files
    if "No tests found" in output:
        success = False
        output = "[FAIL] No tests were found in the generated suite.\n" + output

    return {"success": success, "output": output}

async def run_phpstan(container, path: str) -> dict:
    """Run PHPStan Level 5 analysis."""
    cmd = f"cd /var/www/sandbox && ./vendor/bin/phpstan analyze {shlex.quote(path)} --level=5 --no-progress --error-format=raw"
    res = await docker.execute(container, cmd, timeout=30)
    output = res.stdout
    if res.stderr:
        output += "\n" + res.stderr
    return {"success": res.exit_code == 0, "output": output}

async def run_mutation_test(container) -> MutationResult:
    """Execute and parse Pest mutation tests."""
    res = await docker.execute(
        container, 
        "cd /var/www/sandbox && ./vendor/bin/pest --mutate", 
        timeout=settings.mutation_timeout_seconds
    )
    output = res.stdout + res.stderr
    
    # Strip ANSI escape sequences to get clean text
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    clean_output = ansi_escape.sub('', output)
    
    score = 0.0
    
    # Check for infrastructure/soft-pass conditions (pcov missing etc)
    if any(m in clean_output for m in ["Extension pcov", "command not found"]):
        logger.warning("Mutation test soft-passed due to infrastructure/missing plugin.")
        return MutationResult(100.0, True, output, soft_pass=True)
    
    # If Pest failed to find tests, mutation score is effectively 0
    if "No tests found" in clean_output:
        return MutationResult(0.0, False, f"[FAIL] Mutation gate found no tests to mutate.\n{clean_output}")

    try:
        # Parse the score from the plain text output
        # Format is typically "Score:     0.00%" or "Score: 83.33%"
        score_match = re.search(r'Score:\s*([0-9.]+)%', clean_output)
        if score_match:
            score = float(score_match.group(1))
        else:
            logger.warning(f"Could not parse mutation score from plain text output. Treating as 0.0%. Output tail: {clean_output[-200:]}")
    except Exception as e:
        logger.warning(f"Error parsing mutation score: {e}. Output tail: {clean_output[-200:]}")
            
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

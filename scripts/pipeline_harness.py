#!/usr/bin/env python3
"""
pipeline_harness.py — Manual Stage-by-Stage Pipeline Auditor
=============================================================
Uses REAL DB data and REAL Docker execution.
No mocking, no LLM calls, no faking.

Usage:
    python3 scripts/pipeline_harness.py                            # uses latest DB submission
    python3 scripts/pipeline_harness.py <submission_id>           # uses specific submission
    python3 scripts/pipeline_harness.py --code "<?php ..."        # uses inline code

Stages:
    1. Sandbox Boot       — Does the container start and PHP work?
    2. SQLite Setup       — Does the Laravel .env get configured?
    3. Code Placement     — Does class land in PSR-4 path? (This is where it was failing)
    4. Route Scaffold     — Is an API route registered?
    5. Execute & Capture  — What error does Laravel actually produce?
    6. Classify Error     — Does our classifier read the error correctly?
    7. Patch Application  — Can we apply a hardcoded correct patch?
    8. Pest Test          — Does the test suite run?
"""
import asyncio
import sys
import textwrap
import logging
import time
from sqlalchemy import select

logging.basicConfig(level=logging.WARNING)  # Quiet SQLAlchemy/Docker noise
logger = logging.getLogger("harness")

SEP = "─" * 70

def stage(num: int, name: str):
    print(f"\n{SEP}")
    print(f"  STAGE {num}: {name}")
    print(SEP)

def ok(msg: str):
    print(f"  ✅  {msg}")

def fail(msg: str):
    print(f"  ❌  {msg}")

def info(msg: str):
    print(f"  ℹ️   {msg}")

def show(label: str, content: str, max_lines: int = 15):
    lines = content.strip().splitlines()
    truncated = lines[:max_lines]
    print(f"\n  [{label}]")
    for line in truncated:
        print(f"      {line}")
    if len(lines) > max_lines:
        print(f"      ... ({len(lines) - max_lines} more lines truncated)")


# ─── The Manual "Correct" Patch ──────────────────────────────────────────────
# This is what a perfect AI response should produce for UserController.
# If the system can apply this, the pipeline is healthy.
CORRECT_XML_PATCH = r"""<repair>
  <thought_process>
    The class UserController extends Controller, but Controller base class may
    not be autoloaded. We also need to add the User model import. The method
    getDetails() must be defined on User.
  </thought_process>
  <diagnosis>Fatal: Class App\Http\Controllers\Controller not found. The Controller
  base class is missing, and the User model lacks the getDetails() method.</diagnosis>
  <fix>
    1. Ensured Controller base class exists (setup_sqlite already does this, but
       we patch it explicitly to be safe).
    2. Added missing `use App\Models\User;` import to UserController.
    3. Added `getDetails()` method to the User model.
  </fix>
  <file action="full_replace" path="app/Http/Controllers/UserController.php">
<?php
declare(strict_types=1);
namespace App\Http\Controllers;
use App\Models\User;
use Illuminate\Http\JsonResponse;
class UserController extends Controller
{
    public function show(int $id): JsonResponse
    {
        $user = User::find($id);
        if (!$user) {
            return response()->json(['error' => 'User not found'], 404);
        }
        return response()->json($user->getDetails());
    }
}
  </file>
  <file action="full_replace" path="app/Models/User.php">
<?php
declare(strict_types=1);
namespace App\Models;
use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;
class User extends Model
{
    use HasFactory;
    protected $fillable = ['name', 'email'];
    public function getDetails(): array
    {
        return ['id' => $this->id, 'name' => $this->name];
    }
}
  </file>
  <pest_test>
<?php
use App\Models\User;
covers(App\Http\Controllers\UserController::class);
uses(Illuminate\Foundation\Testing\RefreshDatabase::class);
it('returns 404 for missing user', function () {
    $this->getJson('/api/users/9999')->assertStatus(404);
});
it('returns user details', function () {
    $user = User::create(['name' => 'Test User', 'email' => 'test@example.com']);
    $this->getJson("/api/users/{$user->id}")
        ->assertStatus(200)
        ->assertJsonPath('name', 'Test User');
});
  </pest_test>
</repair>"""


async def run_harness(submission_id: str | None = None, inline_code: str | None = None):
    from api.database import AsyncSessionLocal
    from api.models import Submission
    import api.services.sandbox as sandbox
    from api.services.sandbox import docker
    from api.services.error_classifier import classify_error, format_classified_error_for_llm
    import api.services.patch_service as patch_service
    from api.services.ai_service import _parse_xml_response

    print(f"\n{'═' * 70}")
    print(f"  LARAVIBE PIPELINE HARNESS — LIVE AUDIT")
    print(f"{'═' * 70}")

    # ── Resolve code from DB or inline ───────────────────────────────────────
    code = inline_code
    if not code:
        async with AsyncSessionLocal() as db:
            if submission_id:
                sub = (await db.execute(
                    select(Submission).where(Submission.id == submission_id)
                )).scalar_one_or_none()
                if not sub:
                    fail(f"Submission '{submission_id}' not found in DB.")
                    return
            else:
                sub = (await db.execute(
                    select(Submission).order_by(Submission.created_at.desc())
                )).scalars().first()
                if not sub:
                    fail("No submissions found in DB.")
                    return
            
            code = sub.original_code
            submission_id = sub.id
            info(f"Loaded submission: {submission_id}")
            info(f"Status in DB: {sub.status}")

    show("CODE UNDER TEST", code)

    container_id = None
    container = None

    try:
        # ── STAGE 1: Sandbox Boot ─────────────────────────────────────────────
        stage(1, "Sandbox Boot")
        t0 = time.time()
        container_id = await sandbox.create_sandbox()
        container = sandbox.get_container(container_id)
        ping = await docker.ping(container)
        elapsed = round(time.time() - t0, 2)
        
        if ping:
            ok(f"Container up and responsive in {elapsed}s  (id={container_id[:12]})")
        else:
            fail("Container started but PHP ping failed — Docker image may be broken.")
            return

        # ── STAGE 2: SQLite Setup ─────────────────────────────────────────────
        stage(2, "SQLite Setup & Base Class Bootstrap")
        await sandbox.setup_sqlite(container)
        # Verify the Controller base class exists
        check = await docker.execute(
            container, 
            "cat /var/www/sandbox/app/Http/Controllers/Controller.php",
            timeout=5
        )
        if check.exit_code == 0 and "Controller" in check.stdout:
            ok("Controller base class is present in the sandbox.")
            show("Controller.php", check.stdout, max_lines=6)
        else:
            fail("Controller base class NOT found — this causes every 'Class Controller not found' error.")
            show("Output", check.stdout + check.stderr)

        # ── STAGE 3: Copy Code & Detect Class Info ────────────────────────────
        stage(3, "Code Copy → Class Detection")
        await docker.copy_code(container, code)
        class_info = await sandbox.detect_class_info(container)
        ok(f"FQCN detected:     {class_info.fqcn}")
        ok(f"Destination file:  {class_info.dest_file}")
        ok(f"Route resource:    {class_info.route_resource}")

        # ── STAGE 4: Code Placement (THE CRITICAL STAGE) ──────────────────────
        stage(4, "Code Placement into Laravel PSR-4 (The Broken Stage)")
        placed = await sandbox.place_code_in_laravel(container, class_info)
        if placed:
            ok("Code placed and verified via Tinker. Class is autoloadable.")
        else:
            fail("Place failed. Tinker could NOT resolve the class.")
            # Dig into why
            dest_check = await docker.execute(
                container, f"cat {class_info.dest_file}", timeout=5
            )
            if dest_check.exit_code == 0:
                info("File WAS written to dest, but Tinker failed to resolve it.")
                info("This means the autoloader didn't pick it up.")
                show("Dest file content", dest_check.stdout, max_lines=10)
            else:
                info("File was NOT written to dest at all.")
                show("cp error", dest_check.stderr)

            # Try manual tinker
            tinker_check = await docker.execute(
                container,
                f"cd /var/www/sandbox && php artisan tinker --execute=\"echo class_exists('{class_info.fqcn}') ? 'FOUND' : 'NOT_FOUND';\"",
                timeout=15
            )
            info(f"Manual Tinker class check: {tinker_check.stdout.strip()}")

        # ── STAGE 5: Execute & Capture Error ─────────────────────────────────
        stage(5, "Execute Code & Capture Real Error")
        exec_result = await sandbox.execute_code(container, code)
        raw_error = exec_result.get("error") or exec_result.get("output", "")
        exit_code = exec_result.get("exit_code", 0)

        if exit_code == 0:
            ok(f"Execution succeeded. No error.")
            show("Output", exec_result.get("output", ""))
        else:
            fail(f"Execution failed (exit {exit_code}).")
            show("RAW ERROR", raw_error)

        # ── STAGE 6: Error Classification ─────────────────────────────────────
        stage(6, "Error Classification")
        classified = classify_error(raw_error or "")
        info(f"Category:    {classified.category}")
        info(f"Summary:     {classified.summary}")
        
        # Check if UNKNOWN — that's the classifier not handling it
        if classified.category == "UNKNOWN":
            fail("Classifier returned UNKNOWN — no pattern matched this error.")
            info("The LLM will receive a vague error, leading to hallucination.")
        else:
            ok("Error classified. LLM will receive structured context.")

        # ── STAGE 7: Patch Application ────────────────────────────────────────
        stage(7, "Manual Patch Application (Human-Authored XML)")
        info("Applying a known-correct XML patch to test the patch pipeline...")
        
        try:
            parsed = _parse_xml_response(CORRECT_XML_PATCH)
            info(f"Parsed {len(parsed.patches)} patch(es) from XML.")
            
            results = await patch_service.apply_all(container_id, parsed.patches)
            
            all_ok = all(results.values())
            for path, success in results.items():
                if success:
                    ok(f"Patch applied: {path}")
                else:
                    fail(f"Patch FAILED: {path}")
            
            if not all_ok:
                fail("Not all patches applied. Check lint errors above.")
            else:
                ok("All patches applied successfully.")
                
        except Exception as e:
            fail(f"Patch application raised an exception: {e}")

        # ── STAGE 8: Post-Patch Execution ─────────────────────────────────────
        stage(8, "Post-Patch Execution Check")
        exec_after = await sandbox.execute_code(container, code)
        raw_after = exec_after.get("error") or exec_after.get("output", "")
        exit_after = exec_after.get("exit_code", 0)
        
        if exit_after == 0:
            ok("Post-patch execution: CLEAN. The repair logic worked.")
        else:
            fail(f"Post-patch execution still failing (exit {exit_after}).")
            show("Error after patch", raw_after)

        # ── STAGE 9: Pest Test ────────────────────────────────────────────────
        stage(9, "Pest Test Run")
        info("Writing and running Pest tests...")
        
        try:
            test_result = await sandbox.run_pest_test(container, parsed.pest_test or "")
            if test_result.get("success"):
                ok("Pest tests PASSED.")
            else:
                fail("Pest tests FAILED.")
            show("Pest Output", test_result.get("output", ""))
        except Exception as e:
            fail(f"Pest run raised exception: {e}")

        # ── FINAL VERDICT ─────────────────────────────────────────────────────
        print(f"\n{'═' * 70}")
        print(f"  HARNESS COMPLETE")
        print(f"{'═' * 70}")
        if placed and all_ok and exit_after == 0:
            print("  🏆  VERDICT: Pipeline is HEALTHY. The engine can repair code.")
        else:
            print("  🚨  VERDICT: Pipeline has issues. See failed stages above.")
        print(f"{'═' * 70}\n")

    finally:
        if container_id:
            info(f"Cleaning up container {container_id[:12]}...")
            await sandbox.destroy_sandbox(container_id)


if __name__ == "__main__":
    import os
    os.environ.setdefault("PYTHONPATH", ".")
    
    sub_id = None
    inline = None
    
    args = sys.argv[1:]
    if args:
        if args[0] == "--code" and len(args) > 1:
            inline = args[1]
        else:
            sub_id = args[0]

    asyncio.run(run_harness(submission_id=sub_id, inline_code=inline))

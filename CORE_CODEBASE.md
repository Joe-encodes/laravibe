# LaraVibe Core Codebase

This file contains the core 15 files that define the LaraVibe autonomous repair architecture.

## api/services/repair/orchestrator.py
```python

import asyncio
import json
import logging
import time
from typing import AsyncGenerator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import re

from api.config import get_settings
from api.models import Submission, Iteration
import api.services.boost_service as boost_service
import api.services.patch_service as patch_service
import api.services.escalation_service as escalation_service
import api.services.ai_service as ai_service
import api.services.sandbox as sandbox
from api.services.sandbox import discovery
from . import pipeline, context
from api.logging_config import set_submission_id

logger = logging.getLogger(__name__)
settings = get_settings()


async def run_repair_loop(
    submission_id: str,
    code: str,
    prompt: str | None = None,
    db: AsyncSession | None = None,
    **kwargs,
) -> AsyncGenerator[dict, None]:
    """Orchestrate one full repair lifecycle: sandbox → AI loop → persist results."""
    set_submission_id(submission_id)

    submission = (
        await db.execute(select(Submission).where(Submission.id == submission_id))
    ).scalar_one()
    submission.status = "running"
    await db.commit()

    previous_attempts: list[dict] = []
    created_files: set[str] = set()
    container_id = await sandbox.create_sandbox()

    try:
        yield {"type": "info", "message": "Sandbox ready", "id": container_id}
        container = sandbox.get_container(container_id)

        # ── Bootstrap the Laravel environment once ────────────────────────────
        await sandbox.setup_sqlite(container)
        
        from api.services.sandbox import docker
        await docker.copy_code(container, code)
        
        class_info = await sandbox.detect_class_info(container)
        placed = await sandbox.place_code_in_laravel(container, class_info)
        if not placed:
            logger.warning(f"[{submission_id}] Could not auto-place code. Continuing anyway.")
        await sandbox.scaffold_route(container, class_info)

        primary_target_file = class_info.dest_file
        current_post_mortem = ""

        yield {"type": "info", "message": f"Class detected: {class_info.fqcn}"}

        # ── Repair loop ───────────────────────────────────────────────────────
        max_iters = kwargs.get("max_iterations") or settings.max_iterations
        for i in range(max_iters):
            start_time = time.time()
            iteration_num = i + 1
            yield {"type": "iteration_start", "num": iteration_num}

            # 1. Run the code, capture errors
            exec_res = await sandbox.execute_code(container, code)
            raw_error = exec_res.get("error") or exec_res.get("output", "")
            
            # Filter out known infrastructure noise
            error_logs = "\n".join([
                line for line in raw_error.splitlines() 
                if "boost:" not in line and "CommandNotFoundException" not in line
            ])

            # 2. Gather context
            boost_ctx = await boost_service.get_boost_context(container_id, error_logs, submission_id)
            signatures = await discovery.discover_referenced_signatures(container, code)
            if signatures:
                boost_ctx += f"\n\n## Referenced Class Signatures (Zoom-In)\n{signatures}"
            
            past_repairs = await context.get_similar_repairs(db, error_logs)
            yield {"type": "context_gathered", "error": error_logs[:200]}

            # 3. AI pipeline
            escalation_ctx = escalation_service.build_escalation_context(previous_attempts)
            try:
                ai_resp, models = await asyncio.wait_for(
                    pipeline.run_pipeline(
                        code, error_logs, boost_ctx, previous_attempts, past_repairs, prompt, escalation_ctx, current_post_mortem
                    ),
                    timeout=180.0
                )
            except asyncio.TimeoutError:
                logger.error(f"[{submission_id}] Iteration {iteration_num} timed out during AI pipeline.")
                yield {"type": "error", "message": "AI pipeline timed out after 3 minutes."}
                
                db.add(Iteration(
                    submission_id=submission_id,
                    iteration_num=iteration_num,
                    code_input=code,
                    error_logs=error_logs + "\n\n[SYSTEM] AI pipeline timed out.",
                    ai_response='{"error": "timeout"}',
                    status="failed",
                    duration_ms=int((time.time() - start_time) * 1000),
                ))
                await db.commit()
                continue

            if not ai_resp.patches:
                yield {"type": "error", "message": "AI returned zero patches. Escalating."}
                await escalation_service.escalate_empty_patch(submission_id, iteration_num, ai_resp.raw)
                break

            yield {"type": "ai_thinking", "diagnosis": ai_resp.diagnosis}

            # 4. Apply patches
            apply_res = await patch_service.apply_all(container_id, ai_resp.patches)
            for path, ok in apply_res.items():
                if ok:
                    created_files.add(path)
                    yield {"type": "patch_applied", "path": path}
                else:
                    yield {"type": "patch_skipped", "path": path}

            if not any(apply_res.values()):
                yield {"type": "error", "message": "All patches failed to apply."}
                break

            # 5. Static analysis gate
            for path in (p for p, ok in apply_res.items() if ok and p.endswith(".php")):
                stan_res = await sandbox.run_phpstan(container, path)
                if not stan_res["success"]:
                    error_logs += f"\n\nPHPSTAN ({path}):\n{stan_res['output']}"

            # 6. Pest tests
            pest_code = sandbox.prepare_pest_test(ai_resp.pest_test, class_info.fqcn)
            pest_res = await sandbox.run_pest_test(container, pest_code)
            if not pest_res["success"]:
                error_logs += f"\n\nPEST TEST FAILURE:\n{pest_res['output']}"
                laravel_log = await sandbox.capture_laravel_log(container)
                error_logs += f"\n\nLARAVEL LOG:\n{laravel_log}"
            yield {"type": "pest_result", "success": pest_res["success"]}

            # 6b. Post-Mortem analysis if Pest failed
            if not pest_res["success"]:
                pm_res = await ai_service.get_post_mortem(
                    code,
                    [{"action": p.action, "path": p.target} for p in ai_resp.patches],
                    pest_res["output"],
                    await sandbox.capture_laravel_log(container),
                    boost_ctx
                )
                current_post_mortem = f"Analysis: {pm_res.analysis}\nStrategy: {pm_res.strategy}"
                yield {"type": "info", "message": f"Critic Analysis: {pm_res.category}"}
            else:
                current_post_mortem = ""

            # 7. Mutation gate
            mutation_score = None
            if pest_res["success"] and kwargs.get("use_mutation_gate", True):
                mutation_res = await sandbox.run_mutation_test(container)
                mutation_score = mutation_res.score
                if not mutation_res.passed:
                    error_logs += f"\n\nMUTATION GATE FAILURE (Score: {mutation_score}%):\n{mutation_res.output}"
                yield {"type": "mutation_result", "score": mutation_score, "success": mutation_res.passed}

            # 8. Evaluate outcome
            success = pest_res["success"] and (
                mutation_score is None or mutation_score >= settings.mutation_score_threshold
            )
            it_status = "success" if success else "failed"

            try:
                logger.info(
                    f"[{submission_id}] ITERATION {iteration_num} SUMMARY: "
                    f"Status: {it_status} | "
                    f"Pest: {'PASS' if pest_res['success'] else 'FAIL'} | "
                    f"Mutation: {mutation_score if mutation_score is not None else 'N/A'}% | "
                    f"Models: {json.dumps(models)}"
                )
                db.add(Iteration(
                    submission_id=submission_id,
                    iteration_num=iteration_num,
                    code_input=code,
                    error_logs=error_logs,
                    ai_response=ai_resp.raw,
                    status=it_status,
                    duration_ms=int((time.time() - start_time) * 1000),
                ))

                previous_attempts.append({
                    "diagnosis": ai_resp.diagnosis,
                    "outcome": it_status,
                    "files": list(created_files),
                })

                yield {"type": "iteration_complete", "num": iteration_num, "success": success}

                if success:
                    submission.status = "success"
                    if primary_target_file:
                        submission.final_code = await sandbox.read_file(container, primary_target_file)
                    elif ai_resp.patches:
                        submission.final_code = await sandbox.read_file(container, ai_resp.patches[0].target)
                    else:
                        submission.final_code = code
                    await context.store_repair_success(db, error_logs, ai_resp, iteration_num)
                    await db.commit()
                    yield {"type": "repair_success"}
                    return

                await db.commit()

            except Exception as e:
                await db.rollback()
                logger.error(f"[{submission_id}] DB write failed on iteration {iteration_num}: {e}")
                raise

        # Loop exhausted — mark failed
        try:
            submission.status = "failed"
            await db.commit()
        except Exception:
            await db.rollback()
        yield {"type": "repair_failed"}

    except Exception as e:
        await db.rollback()
        logger.exception(f"[{submission_id}] Fatal error: {e}")
        try:
            submission.status = "failed"
            submission.error_summary = str(e)
            await db.commit()
        except Exception:
            pass
        yield {"type": "error", "message": str(e)}
    finally:
        await sandbox.destroy_sandbox(container_id)

```

## api/services/repair/pipeline.py
```python

import logging
import api.services.ai_service as ai_service

logger = logging.getLogger(__name__)

async def run_pipeline(code, error, boost, prev, past, prompt, escalation_ctx, post_mortem=None):
    """Planner -> Verifier -> Executor -> Reviewer pipeline."""
    # 1. Planner: Analyze and plan
    plan_result = await ai_service.get_plan(code, error, boost, prev, past, post_mortem)
    
    # 2. Verifier: Verify the plan for potential flaws
    verify_result = await ai_service.verify_plan(code, error, boost, plan_result.raw, prev)
    plan_to_use = verify_result.approved_plan or plan_result.data
    
    # 3. Executor: Generate the code/patches
    exec_result = await ai_service.execute_plan(code, error, boost, plan_to_use, escalation_ctx, prompt)
    
    # 4. Reviewer: Final check on the generated code
    review_result = await ai_service.review_output(exec_result.response.raw, plan_to_use)
    
    final_resp = review_result.validated_output or exec_result.response
    models = {
        "planner": plan_result.model_used,
        "executor": exec_result.model_used,
        "reviewer": review_result.model_used
    }
    return final_resp, models

```

## api/services/escalation_service.py
```python

"""
api/services/escalation_service.py — Stuck loop detection and escalation.

Handles Phase 6: detects when the LLM is stuck in a loop of identical
diagnoses or failing patches, and injects stern instructions.

Escalation triggers:
  1. Repeated identical diagnoses (fuzzy match, threshold=2)
  2. Back-to-back patch application failures
  3. create_file was used but the original file still fails
  4. Dependency Guard: AI tries to create_file for a path it already created
"""

import re

# Minimum consecutive identical diagnoses before escalation
STUCK_DIAGNOSIS_THRESHOLD = 2


def _get_words(text: str) -> set:
    return set(re.findall(r'\b\w+\b', text.lower()))


def is_fuzzy_match(text1: str, text2: str, threshold: float = 0.70) -> bool:
    w1 = _get_words(text1)
    w2 = _get_words(text2)
    if not w1 or not w2:
        return text1 == text2
    overlap = len(w1.intersection(w2))
    return (overlap / len(w1) >= threshold) and (overlap / len(w2) >= threshold)


def should_force_full_replace(previous_attempts: list[dict]) -> bool:
    """If the LLM has tried to patch twice and failed both times, force full_replace."""
    if len(previous_attempts) < 2:
        return False

    last_two = previous_attempts[-2:]
    return all(a.get("patch_status", "").startswith("FAILED") for a in last_two)


def _last_action_was_create_file(previous_attempts: list[dict]) -> bool:
    """Check if the most recent action included create_file but NOT full_replace."""
    if not previous_attempts:
        return False
    last_action = previous_attempts[-1].get("action", "")
    return "create_file" in last_action and "full_replace" not in last_action


def _get_all_created_files(previous_attempts: list[dict]) -> list[str]:
    """
    Return all file paths the AI successfully created in previous attempts.
    
    Paths are stored in previous_attempts[*]['created_files'] — a list of relative
    paths added by orchestrator when patch_result.created_files is non-empty.
    """
    seen: dict[str, int] = {}
    for attempt in previous_attempts:
        for path in attempt.get("created_files", []):
            seen[path] = seen.get(path, 0) + 1
    return list(seen.keys())


def build_escalation_context(previous_attempts: list[dict]) -> str:
    """Build a stern prompt piece when the LLM is stuck."""
    context = ""

    # 1. Stuck diagnoses (fuzzy match) — trigger after just 2 identical
    if len(previous_attempts) >= STUCK_DIAGNOSIS_THRESHOLD:
        window = previous_attempts[-STUCK_DIAGNOSIS_THRESHOLD:]
        recent = [a.get("diagnosis", "") for a in window]
        recent = [d for d in recent if d.strip()]

        if len(recent) >= STUCK_DIAGNOSIS_THRESHOLD:
            all_same = all(is_fuzzy_match(recent[0], d) for d in recent[1:])

            if all_same:
                context += (
                    f"CRITICAL: Your last {len(recent)} diagnoses were essentially IDENTICAL.\n"
                    f"You keep diagnosing: '{recent[0]}'.\n"
                    "This approach is NOT WORKING. You MUST try a completely different logical approach. "
                    "Stop repeating the same reasoning.\n\n"
                )

    # 2. Patch failures
    if should_force_full_replace(previous_attempts):
        context += (
            "CRITICAL: Your recent patches failed to apply because the 'target' text was not found.\n"
            "DO NOT use action='replace' anymore for this file. You MUST use action='full_replace' "
            "and output the entire complete corrected file.\n\n"
        )

    # 3. create_file without fixing the original file
    if _last_action_was_create_file(previous_attempts):
        context += (
            "IMPORTANT: In the previous iteration you created a dependency file (e.g. a Model or Migration) "
            "but you did NOT fix the original submitted controller/class file.\n"
            "The dependency file now EXISTS in the sandbox. Your ONLY job now is to output a `full_replace` "
            "patch for the original submitted file. Do NOT create the dependency again.\n"
            "Include BOTH the correct `use` imports and any code changes needed in the original file.\n\n"
        )

    # 4. Dependency Guard: AI tried to create the same file twice
    created_paths = _get_all_created_files(previous_attempts)
    if created_paths:
        paths_str = ", ".join(f"`{p}`" for p in created_paths)
        context += (
            f"CRITICAL — DEPENDENCY ALREADY EXISTS IN SANDBOX: You have already created {paths_str} "
            "in a previous iteration. These files are on the container filesystem RIGHT NOW. "
            "DO NOT emit another create_file for them — it will be ignored and waste this iteration. "
            "Your ONLY job is to fix the `use` imports and business logic in the original submitted file.\n\n"
        )

    return context.strip()


async def escalate_empty_patch(submission_id: str, iteration: int, raw_response: str):
    """
    Called when the AI returns a valid-looking XML block but with ZERO <file> tags.
    This usually means it's stuck or refusing to output code.
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.error(f"[{submission_id}] ESCALATION: AI returned zero patches in iteration {iteration}")
    # In a real system, we might alert a human or try a "nuclear" prompt reset.
    # For now, we just log it; the orchestrator will raise PatchApplicationError.



```

## api/services/ai_service.py
```python
"""
api/services/ai_service.py — LLM integration with multi-provider fallback.

Architecture:
  - Provider dispatch:  _call_openai_compatible(), _call_anthropic()
  - Pool routing:       _call_role_pool()
  - XML parsing:        _parse_xml_response()  ← replaces JSON escaping hell
  - Role functions:     get_plan(), verify_plan(), execute_plan(), review_output()
  - Legacy path:        get_repair() (kept for USE_ROLE_PIPELINE=false)

All Executor/Reviewer output is XML. Planner/Verifier output is JSON (no PHP
content inside, so JSON is safe for them).
"""
from __future__ import annotations

import json
import logging
import pathlib
import re
from dataclasses import dataclass

import httpx
from tenacity import (
    retry, retry_if_exception_type,
    stop_after_attempt, wait_exponential, before_sleep_log,
)

try:
    import openai
    AsyncOpenAI = openai.AsyncOpenAI
except ImportError as e:
    raise ImportError(f"OpenAI library not installed. Please install with: pip install openai. Error: {e}")
except AttributeError as e:
    raise ImportError(f"AsyncOpenAI not available in openai library. Please upgrade openai. Error: {e}")

from api.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Prompt templates (loaded once at import) ──────────────────────────────────

_PROMPTS = pathlib.Path(__file__).parent.parent / "prompts"

def _load(name: str) -> str:
    return (_PROMPTS / name).read_text(encoding="utf-8")

_PLAN_PROMPT      = _load("role_plan_prompt.md")
_VERIFY_PROMPT    = _load("role_verify_prompt.md")
_EXECUTE_PROMPT   = _load("role_execute_prompt.md")
_REVIEW_PROMPT    = _load("role_review_prompt.md")
_POST_MORTEM_PROMPT = _load("role_post_mortem_prompt.md")


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PatchSpec:
    action:      str        # "full_replace" | "create_file"
    target:      str | None
    replacement: str
    filename:    str | None


@dataclass
class AIRepairResponse:
    thought_process: str | None
    diagnosis:       str
    fix_description: str
    patches:         list[PatchSpec]
    pest_test:       str
    raw:             str   # original LLM output
    prompt:          str
    model_used:      str = "unknown"


@dataclass
class PlanResult:
    raw:        str
    data:       dict
    model_used: str


@dataclass
class VerifyResult:
    verdict:          str          # "APPROVED" | "REJECT"
    approved_plan:    dict | None
    corrections_made: list[str]
    reason:           str
    model_used:       str
    raw:              str


@dataclass
class ExecuteResult:
    response:   AIRepairResponse
    model_used: str


@dataclass
class ReviewResult:
    verdict:                 str          # "APPROVED" | "ESCALATE"
    retry_count:             int
    repairs_made:            list[str]
    validated_output:        AIRepairResponse | None
    escalation_reason:       str
    evidence_for_next_cycle: dict
    model_used:              str


@dataclass
class PostMortemResult:
    analysis:        str
    category:        str
    strategy:        str
    files_implicated: list[str]
    model_used:      str
    raw:             str


class AIServiceError(Exception):
    pass


ALLOWED_PATCH_ACTIONS = {"full_replace", "create_file"}


# ── Provider registry ─────────────────────────────────────────────────────────

_PROVIDERS: dict[str, dict] = {
    "qwen":      {"base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "key_attr": "dashscope_api_key",  "default_model": "qwen3-max"},
    "dashscope": {"base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "key_attr": "dashscope_api_key",  "default_model": "qwen3-max"},
    "nvidia":    {"base_url": "https://integrate.api.nvidia.com/v1",                    "key_attr": "nvidia_api_key",     "default_model": "meta/llama-3.3-70b-instruct"},
    "cerebras":  {"base_url": "https://api.cerebras.ai/v1",                             "key_attr": "cerebras_api_key",   "default_model": "llama-3.3-70b"},
    "groq":      {"base_url": "https://api.groq.com/openai/v1",                         "key_attr": "groq_api_key",       "default_model": "llama-3.3-70b-versatile"},
    "gemini":    {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/","key_attr": "gemini_api_key",     "default_model": "gemini-2.0-flash"},
    "deepseek":  {"base_url": "https://api.deepseek.com",                               "key_attr": "deepseek_api_key",   "default_model": "deepseek-coder"},
    "ollama":    {"base_url": None,                                                      "key_attr": None,                 "default_model": "qwen2.5-coder:7b"},
    "openai":    {"base_url": None,                                                      "key_attr": "openai_api_key",     "default_model": "gpt-4o"},
}

# Providers that support native json_object mode (Planner/Verifier only)
_JSON_MODE_PROVIDERS = {"openai", "deepseek", "groq", "nvidia", "qwen", "dashscope"}

# ── Model pools ───────────────────────────────────────────────────────────────
# Each pool = [(provider, model), ...] ordered by preference.
# Nvidia 40 RPM → reserved for Executor. Gemini low RPM → Planner/Verifier only.

def _build_pool_from_config(raw_pool: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Only include providers with active API keys."""
    result = []
    for provider, model in raw_pool:
        cfg = _PROVIDERS.get(provider, {})
        key_attr = cfg.get("key_attr")
        if key_attr is None:  # ollama — no key needed
            result.append((provider, model))
        elif getattr(settings, key_attr, ""):  # key is set
            result.append((provider, model))
        else:
            logger.debug(f"[AI Pool] Skipping {provider}/{model} — no API key configured")
    return result

PLANNER_POOL: list[tuple[str, str]] = _build_pool_from_config([
    ("groq",      "llama-3.3-70b-versatile"),      # Strong logic
    ("cerebras",  "llama-3.3-70b"),                # Blazing fast
    # ("gemini",    "gemini-2.0-flash"),             # Stable, fast - API issues
])

VERIFIER_POOL: list[tuple[str, str]] = _build_pool_from_config([
    ("groq",      "llama-3.3-70b-versatile"),
    ("cerebras",  "llama-3.3-70b"),
    # ("gemini",    "gemini-2.0-flash"),
])

EXECUTOR_POOL: list[tuple[str, str]] = _build_pool_from_config([
    ("nvidia",    "meta/llama-3.3-70b-instruct"),
    ("groq",      "llama-3.3-70b-versatile"),
    ("cerebras",  "llama-3.3-70b"),
])

REVIEWER_POOL: list[tuple[str, str]] = _build_pool_from_config([
    ("groq",      "llama-3.3-70b-versatile"),
    ("cerebras",  "llama-3.3-70b"),
    # ("gemini",    "gemini-2.0-flash"),
])

POST_MORTEM_POOL: list[tuple[str, str]] = _build_pool_from_config([
    ("groq",      "llama-3.3-70b-versatile"),
    # ("gemini",    "gemini-2.0-flash"),
])


# ── Provider calls ────────────────────────────────────────────────────────────

async def _call_openai_compatible(
    prompt: str,
    provider: str,
    model: str | None = None,
    json_mode: bool = False,
) -> str:
    """Single entry point for all OpenAI-compatible providers."""
    cfg = _PROVIDERS.get(provider)
    if not cfg:
        raise AIServiceError(f"Unknown provider: {provider}")

    if provider == "ollama":
        api_key, base_url = "ollama", f"{settings.ollama_base_url}/v1"
    else:
        api_key  = getattr(settings, cfg["key_attr"]) if cfg.get("key_attr") else ""
        base_url = cfg["base_url"]

    if not base_url:
        raise AIServiceError(f"Provider {provider} has no base_url configured")

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        max_retries=0,
        timeout=60.0,
    )

    kwargs: dict = {
        "model":       model or cfg["default_model"],
        "temperature": 0.0 if json_mode else settings.ai_temperature,
        "messages":    [{"role": "user", "content": prompt}],
    }
    if json_mode and provider in _JSON_MODE_PROVIDERS:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        resp = await client.chat.completions.create(**kwargs)
    except Exception as exc:
        msg = str(exc).lower()
        if "response_format" in kwargs and any(k in msg for k in (
            "extra_forbidden", "response_format", "unsupported", "422"
        )):
            logger.warning(f"[AI] {provider}/{kwargs['model']} rejected JSON mode — retrying plain.")
            kwargs.pop("response_format", None)
            resp = await client.chat.completions.create(**kwargs)
        else:
            import traceback
            logger.error(f"[AI] {provider}/{kwargs['model']} fatal error: {exc}\n{traceback.format_exc()}")
            raise

    return resp.choices[0].message.content


async def _call_anthropic(prompt: str, model: str | None = None) -> str:
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    msg = await client.messages.create(
        model=model or settings.ai_model,
        max_tokens=4096,
        temperature=settings.ai_temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


# ── Pool routing ──────────────────────────────────────────────────────────────

async def _call_role_pool(
    prompt: str,
    pool: list[tuple[str, str]],
    role_name: str,
    json_mode: bool = False,
) -> tuple[str, str]:
    """
    Try providers in pool order. Returns (response_text, model_identifier).
    Raises AIServiceError if every provider fails.
    """
    last_error: Exception | None = None
    for provider, model in pool:
        try:
            logger.info(f"[AI/{role_name}] Trying {provider}/{model}")
            text = await _call_openai_compatible(prompt, provider, model=model, json_mode=json_mode)
            if json_mode and "{" not in text:
                raise ValueError(f"{provider}/{model}: no JSON object in response")
            return text, f"{provider}/{model}"
        except Exception as exc:
            logger.warning(f"[AI/{role_name}] {provider}/{model} failed: {exc}")
            last_error = exc

    raise AIServiceError(f"[{role_name}] All providers failed. Last: {last_error}")


# ── XML parsing (replaces JSON escape hell) ───────────────────────────────────

def _strip_think_blocks(raw: str) -> str:
    """Remove DeepSeek R1 <think>...</think> chain-of-thought blocks."""
    return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()


def _parse_xml_response(raw: str) -> AIRepairResponse:
    """
    Parse the Executor/Reviewer XML output into an AIRepairResponse.

    Expected structure:
        <repair>
          <diagnosis>...</diagnosis>
          <fix>...</fix>
          <thought_process>...</thought_process>
          <file action="full_replace" path="...">...raw PHP...</file>
          <pest_test>...raw PHP...</pest_test>
        </repair>

    No JSON. No escaping. PHP arrives raw.
    """
    text = _strip_think_blocks(raw)

    def _tag(name: str) -> str:
        m = re.search(rf"<{name}>(.*?)</{name}>", text, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else ""

    diagnosis       = _tag("diagnosis")
    fix_description = _tag("fix")
    thought_process = _tag("thought_process")
    pest_raw        = _tag("pest_test")

    # Parse <file action="..." path="...">...</file> (Supports both single and double quotes)
    file_pattern = re.compile(
        r'<file\s+action=(["\'])(.*?)\1\s+path=(["\'])(.*?)\3>(.*?)</file>',
        re.DOTALL | re.IGNORECASE,
    )
    patches: list[PatchSpec] = []
    for _, action, _, path, content in file_pattern.findall(text):
        action = action.strip()
        path   = path.strip()
        if action not in ALLOWED_PATCH_ACTIONS:
            action = "full_replace" if "Controller" in path else "create_file"
        patches.append(PatchSpec(
            action=action,
            target=path,
            replacement=_sanitize_php(content.strip()),
            filename=path,
        ))

    return AIRepairResponse(
        thought_process=thought_process or None,
        diagnosis=diagnosis,
        fix_description=fix_description,
        patches=patches,
        pest_test=_sanitize_php(pest_raw),
        raw=raw,
        prompt="",
    )


def _sanitize_php(code: str) -> str:
    """
    Minimal post-processing on raw PHP extracted from XML.
    XML preserves raw content so we only need to handle two edge cases:
      1. Literal '\\n' strings (model forgot it was writing raw XML, fell back to JSON escaping)
      2. Named-class migrations → anonymous class syntax
    """
    if not code:
        return code

    # Edge case: model output literal \\n instead of real newlines
    if "<?php\\n" in code or ("\\n" in code and "\n" not in code.strip()):
        code = code.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")

    # Enforce anonymous migration syntax
    if "extends Migration" in code and "return new class extends Migration" not in code:
        code = re.sub(
            r"class\s+\w+\s+extends\s+Migration",
            "return new class extends Migration",
            code,
            flags=re.MULTILINE,
        )

    return code


# ── JSON helpers (Planner/Verifier only) ──────────────────────────────────────

def _extract_json_object(raw: str) -> str:
    """
    Extract the outermost JSON object from raw LLM output.
    Handles <think> blocks, prose wrappers, and markdown fences.
    Used only for Planner/Verifier responses (no PHP inside).
    """
    text = _strip_think_blocks(raw)
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in LLM response")

    depth, in_string, escape = 0, False, False
    for i, ch in enumerate(text[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    raise ValueError("Unbalanced braces in LLM JSON response")


def _parse_json_safe(raw: str) -> dict:
    """Parse JSON from LLM output, with one escape-fix fallback."""
    json_str = _extract_json_object(raw)
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        # Fix unescaped backslashes (PHP namespaces in Planner output)
        fixed = re.sub(r'(?<!\\)\\(?!["\\/bfnrtu])', r'\\\\', json_str)
        return json.loads(fixed)


# ── Prompt builders ───────────────────────────────────────────────────────────

def _fmt_previous_attempts(previous_attempts: list[dict]) -> str:
    if not previous_attempts:
        return "None — this is the first attempt."
    lines = []
    for i, a in enumerate(previous_attempts):
        created = a.get("created_files", [])
        parts = [
            f"Attempt {i + 1}:",
            f"  - Action:    {a.get('action', '?')}",
            f"  - Diagnosis: {a.get('diagnosis', '?')}",
            f"  - Fix:       {a.get('fix_description', '?')}",
            f"  - Outcome:   {a.get('outcome', 'unknown')}",
        ]
        if created:
            parts.append("  - Files in container: " + ", ".join(created))
        if a.get("escalation_evidence"):
            parts.append(f"  - Reviewer evidence: {a['escalation_evidence']}")
        lines.append("\n".join(parts))
    return "\n\n".join(lines)


def _build_role_prompt(template: str, **kwargs: str) -> str:
    result = template
    for key, value in kwargs.items():
        result = result.replace(f"{{{key}}}", value or "")
    return result


# ── Role 1: Planner ───────────────────────────────────────────────────────────

async def get_plan(
    code: str,
    error: str,
    boost_context: str,
    previous_attempts: list[dict],
    similar_past_repairs: str = "",
    post_mortem: str = "",
) -> PlanResult:
    """Classify the error and produce a structured JSON repair plan."""
    prompt = _build_role_prompt(
        _PLAN_PROMPT,
        code=code,
        error=error,
        boost_context=boost_context,
        previous_attempts=_fmt_previous_attempts(previous_attempts),
        similar_past_repairs=similar_past_repairs,
        post_mortem=post_mortem,
    )
    raw, model_used = await _call_role_pool(prompt, PLANNER_POOL, "Planner", json_mode=True)
    data = _parse_json_safe(raw)
    logger.info(f"[Planner] {data.get('error_classification')} confidence={data.get('plan_confidence')}")
    return PlanResult(raw=raw, data=data, model_used=model_used)


# ── Role 2: Verifier ──────────────────────────────────────────────────────────

async def verify_plan(
    code: str,
    error: str,
    boost_context: str,
    planner_output: str,
    previous_attempts: list[dict] | None = None,
) -> VerifyResult:
    """Validate and optionally correct the Planner's plan."""
    prompt = _build_role_prompt(
        _VERIFY_PROMPT,
        code=code,
        error=error,
        boost_context=boost_context,
        planner_output=planner_output,
        previous_attempts=_fmt_previous_attempts(previous_attempts or []),
    )
    raw, model_used = await _call_role_pool(prompt, VERIFIER_POOL, "Verifier", json_mode=True)
    data = _parse_json_safe(raw)

    verdict          = data.get("verdict", "APPROVED")
    approved_plan    = data.get("approved_plan") if verdict == "APPROVED" else None
    corrections_made = data.get("corrections_made", [])
    reason           = data.get("reason", "")

    if corrections_made:
        logger.info(f"[Verifier] Corrections: {corrections_made}")

    return VerifyResult(
        verdict=verdict,
        approved_plan=approved_plan,
        corrections_made=corrections_made,
        reason=reason,
        model_used=model_used,
        raw=raw,
    )


# ── Role 3: Executor ──────────────────────────────────────────────────────────

async def execute_plan(
    code: str,
    error: str,
    boost_context: str,
    approved_plan: dict,
    escalation_context: str = "",
    user_prompt: str | None = None,
) -> ExecuteResult:
    """Generate all PHP code from the approved plan. Returns XML output."""
    plan_str = json.dumps(approved_plan, ensure_ascii=False, indent=2)
    prompt = _build_role_prompt(
        _EXECUTE_PROMPT,
        code=code,
        error=error,
        boost_context=boost_context,
        approved_plan=plan_str,
        escalation_context=escalation_context,
        user_prompt=user_prompt or "",
    )
    raw, model_used = await _call_role_pool(prompt, EXECUTOR_POOL, "Executor", json_mode=False)
    resp = _parse_xml_response(raw)
    resp.prompt     = prompt
    resp.model_used = model_used
    logger.info(f"[Executor] {len(resp.patches)} patch(es) via {model_used}")
    return ExecuteResult(response=resp, model_used=model_used)


# ── Role 4: Reviewer ──────────────────────────────────────────────────────────

async def review_output(
    executor_output_raw: str,
    approved_plan: dict,
    retry_count: int = 0,
) -> ReviewResult:
    """
    Validate Executor XML output format and structure.
    Returns ReviewResult with verdict APPROVED or ESCALATE.
    The Reviewer's own output is also XML.
    """
    plan_str = json.dumps(approved_plan, ensure_ascii=False, indent=2)
    prompt = _build_role_prompt(
        _REVIEW_PROMPT,
        executor_output=executor_output_raw,
        approved_plan=plan_str,
        retry_count=str(retry_count),
    )
    raw, model_used = await _call_role_pool(prompt, REVIEWER_POOL, "Reviewer", json_mode=False)

    # Parse Reviewer XML envelope
    verdict_match    = re.search(r'<review[^>]*verdict="([^"]+)"',    raw, re.IGNORECASE)
    retry_match      = re.search(r'<review[^>]*retry_count="(\d+)"',  raw, re.IGNORECASE)
    verdict          = (verdict_match.group(1).upper() if verdict_match else "ESCALATE")
    parsed_retry     = int(retry_match.group(1)) if retry_match else retry_count

    repairs = re.findall(r"<repair_action>(.*?)</repair_action>", raw, re.DOTALL | re.IGNORECASE)

    validated_resp: AIRepairResponse | None = None
    if verdict == "APPROVED":
        vo_match = re.search(r"<validated_output>(.*?)</validated_output>", raw, re.DOTALL | re.IGNORECASE)
        if vo_match:
            try:
                validated_resp = _parse_xml_response(vo_match.group(1))
                # Guard: if Reviewer dropped all patches, restore originals
                if not validated_resp.patches:
                    logger.warning("[Reviewer] Empty patches in validated_output — restoring originals.")
                    validated_resp.patches = _parse_xml_response(executor_output_raw).patches
                validated_resp.model_used = model_used
            except Exception as exc:
                logger.warning(f"[Reviewer] Could not re-parse validated_output: {exc} — escalating.")
                verdict = "ESCALATE"

    escalation_reason = ""
    evidence: dict    = {}
    if verdict == "ESCALATE":
        r = re.search(r"<escalation_reason>(.*?)</escalation_reason>", raw, re.DOTALL | re.IGNORECASE)
        escalation_reason = r.group(1).strip() if r else ""
        ev = re.search(r"<evidence_for_next_cycle>(.*?)</evidence_for_next_cycle>", raw, re.DOTALL | re.IGNORECASE)
        if ev:
            ec = ev.group(1)
            def _ev_tag(name: str) -> str:
                m = re.search(rf"<{name}>(.*?)</{name}>", ec, re.DOTALL | re.IGNORECASE)
                return m.group(1).strip() if m else ""
            evidence = {
                "what_failed":    _ev_tag("what_failed"),
                "what_was_tried": _ev_tag("what_was_tried"),
                "recommendation": _ev_tag("recommendation"),
            }

    if repairs:
        logger.info(f"[Reviewer] Inline repairs: {repairs}")

    return ReviewResult(
        verdict=verdict,
        retry_count=parsed_retry,
        repairs_made=repairs,
        validated_output=validated_resp,
        escalation_reason=escalation_reason,
        evidence_for_next_cycle=evidence,
        model_used=model_used,
    )


# ── Role 5: Post-Mortem ───────────────────────────────────────────────────────

async def get_post_mortem(
    code: str,
    failed_patches: list[dict],
    pest_output: str,
    laravel_log: str,
    boost_context: str,
) -> PostMortemResult:
    """Analyze a failed repair attempt and generate a fix strategy."""
    prompt = _build_role_prompt(
        _POST_MORTEM_PROMPT,
        code=code,
        failed_patches=json.dumps(failed_patches, indent=2),
        pest_output=pest_output,
        laravel_log=laravel_log,
        boost_context=boost_context,
    )
    raw, model_used = await _call_role_pool(prompt, POST_MORTEM_POOL, "PostMortem", json_mode=True)
    data = _parse_json_safe(raw)
    
    return PostMortemResult(
        analysis=data.get("failure_analysis", ""),
        category=data.get("root_cause_category", "logic"),
        strategy=data.get("fix_strategy", ""),
        files_implicated=data.get("files_implicated", []),
        model_used=model_used,
        raw=raw,
    )

```

## api/services/patch_service.py
```python

"""
api/services/patch_service.py — Container-side code persistence with security guards.

Security model:
  - FORBIDDEN_FILES: filenames the AI must never overwrite
  - FORBIDDEN_DIRS:  directories that are off-limits
  - Path normalisation via posixpath.normpath blocks traversal (../../../.env)
  - PHP syntax is verified in /tmp before writing to the real destination

Failure policy:
  - Per-patch failures are logged and recorded but DO NOT abort remaining patches.
  - Only a complete write failure raises PatchApplicationError.
"""
import logging
import posixpath
from typing import Dict, List

import api.services.sandbox as sandbox

logger = logging.getLogger(__name__)

FORBIDDEN_FILES = {
    ".env", "composer.json", "composer.lock",
    "artisan", "package.json", "phpunit.xml", "pest.php",
}

FORBIDDEN_DIRS = {
    "vendor/", "node_modules/", "storage/", "bootstrap/cache/",
}


class PatchApplicationError(Exception):
    """Raised only when every patch in a batch failed — nothing was written."""
    pass


async def apply_all(container_id: str, patches: List) -> Dict[str, bool]:
    """
    Apply a list of PatchSpec patches to the sandbox container.

    Returns a dict mapping filename → True/False (success/failure).
    Individual patch failures do NOT raise; only a total-failure raises.
    """
    results: dict[str, bool] = {}
    container = sandbox.get_container(container_id)

    for patch in patches:
        filename = patch.filename or patch.target
        if not filename:
            logger.warning("[Patch] Skipping patch with no filename/target.")
            continue

        # ── Security: normalize and validate path ────────────────────────────
        safe_path = posixpath.normpath(filename).lstrip("/")

        if (
            any(safe_path.endswith(f) for f in FORBIDDEN_FILES)
            or any(safe_path.startswith(d) for d in FORBIDDEN_DIRS)
            or ".." in safe_path
        ):
            logger.error(f"[Patch] BLOCKED forbidden path: {filename!r}")
            results[filename] = False
            continue

        # ── Lint in /tmp before touching the real destination ────────────────
        try:
            tmp_path = f"/tmp/lint_{abs(hash(filename)) % 10**9}.php"
            await sandbox.write_file(container, tmp_path, patch.replacement)
            lint_ok, lint_msg = await sandbox.lint_php(container, tmp_path)

            if not lint_ok:
                logger.error(f"[Patch] Lint failed for {filename!r}: {lint_msg}")
                results[filename] = False
                continue  # skip this file, try the next patch

            # ── Write to real destination ────────────────────────────────────
            await sandbox.write_file(container, filename, patch.replacement)
            logger.info(f"[Patch] Applied {patch.action!r} → {filename!r}")
            results[filename] = True

        except Exception as exc:
            logger.error(f"[Patch] Write failed for {filename!r}: {exc}")
            results[filename] = False

    if results and not any(results.values()):
        raise PatchApplicationError(
            f"Every patch failed to apply: {list(results.keys())}"
        )

    return results

```

## api/services/sandbox/__init__.py
```python

from .manager import create_sandbox, destroy_sandbox, get_container
from .laravel import detect_class_info, setup_sqlite, place_code_in_laravel, scaffold_route, ClassInfo, execute_code
from .testing import run_pest_test, run_phpstan, run_mutation_test, capture_laravel_log, MutationResult
from .filesystem import write_file, read_file, lint_php, prepare_pest_test

__all__ = [
    'create_sandbox', 'destroy_sandbox', 'get_container',
    'detect_class_info', 'setup_sqlite', 'place_code_in_laravel', 'scaffold_route', 'ClassInfo', 'execute_code',
    'run_pest_test', 'run_phpstan', 'run_mutation_test', 'capture_laravel_log', 'MutationResult',
    'write_file', 'read_file', 'lint_php', 'prepare_pest_test'
]

```

## api/services/sandbox/docker.py
```python

"""
api/services/docker.py — Container lifecycle management via docker-py.

Responsibilities:
- create_container()  spin up a fresh laravel-sandbox container
- copy_code()         write PHP code to /submitted/code.php inside container
- execute()           run a shell command, return stdout/stderr/exit_code
- destroy()           stop + remove the container (always call in finally)
- health_check()      confirm Docker daemon is reachable
"""
import asyncio
import io
import tarfile
import time
import logging
from dataclasses import dataclass

import docker
from docker.errors import DockerException, NotFound

from api.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int

    @property
    def is_timeout(self) -> bool:
        return self.exit_code == 124

    @property
    def has_php_fatal(self) -> bool:
        """PHP fatal errors don't always produce non-zero exit codes — check text too."""
        combined = (self.stdout + self.stderr).lower()
        return any(kw in combined for kw in [
            "fatal error", "parse error", "uncaught exception",
            "class not found", "undefined function", "call to undefined"
        ])


_docker_client = None


def _get_client() -> docker.DockerClient:
    """Return a shared Docker client. Raises DockerException if daemon unreachable."""
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.from_env(timeout=60)
    return _docker_client


async def is_alive(container) -> bool:
    """Check if container is still running and healthy."""
    def _check():
        try:
            container.reload()  # refresh container state
            return container.status == "running"
        except Exception:
            return False

    return await asyncio.to_thread(_check)


async def ping(container, retries: int = 3) -> bool:
    """
    Run a fast no-op command to ensure the container is responsive.
    """
    for attempt in range(retries):
        try:
            result = await execute(container, "php -v", timeout=15)
            if result.exit_code == 0:
                if attempt > 0:
                    logger.info(f"[{container.short_id}] Sandbox responded on attempt {attempt + 1}")
                return True
        except Exception as e:
            logger.warning(f"[{container.short_id}] Ping attempt {attempt + 1} failed: {e}")
        
        if attempt < retries - 1:
            await asyncio.sleep(1)

    return False


async def create_container() -> docker.models.containers.Container:
    """
    Spin up a fresh laravel-sandbox container with strict resource limits.
    """
    def _create():
        client = _get_client()
        container = client.containers.run(
            image=settings.docker_image_name,
            detach=True,
            network_mode="none",              # no network access from inside container
            mem_limit=settings.container_memory_limit,
            nano_cpus=int(settings.container_cpu_limit * 1e9),
            pids_limit=settings.container_pid_limit,
            read_only=False,                  # needs write access for composer / artisan
            security_opt=["no-new-privileges:true"],
            command="sleep infinity",         # keep alive until we exec into it
            remove=False,                     # we destroy manually in finally block
        )
        logger.info(f"Container created: {container.short_id}")
        return container

    return await asyncio.to_thread(_create)


async def copy_code(container, code: str) -> None:
    """Write `code` to /submitted/code.php inside the running container."""
    await copy_file(container, "/submitted/code.php", code)


async def copy_file(container, dest_path: str, content: str) -> None:
    """Write `content` to `dest_path` inside the running container."""
    def _copy():
        import pathlib
        import posixpath
        content_bytes = content.encode("utf-8")

        # If path is relative, it's relative to the Laravel root
        if not posixpath.isabs(dest_path):
            abs_dest_path = posixpath.join("/var/www/sandbox", dest_path)
        else:
            abs_dest_path = dest_path

        # Use posixpath for container-side dir (container is always Linux)
        dest_dir = posixpath.dirname(abs_dest_path)
        filename = pathlib.PurePosixPath(abs_dest_path).name

        # Step 1: Ensure the directory exists BEFORE put_archive.
        # Check the exit code — if this fails, put_archive will 404.
        # Both exec_run and put_archive now use absolute paths to prevent WORKDIR vs Root mismatches.
        mkdir_result = container.exec_run(
            f"mkdir -p {dest_dir}",
            user="root"
        )
        if mkdir_result.exit_code != 0:
            raise RuntimeError(
                f"mkdir -p {dest_dir} failed in container "
                f"(exit {mkdir_result.exit_code}): "
                f"{(mkdir_result.output or b'').decode(errors='replace')}"
            )

        # Step 2: Build the in-memory tar archive.
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            info = tarfile.TarInfo(name=filename)
            info.size = len(content_bytes)
            tar.addfile(info, io.BytesIO(content_bytes))
        tar_buffer.seek(0)

        # Step 3: Stream the archive into the now-guaranteed directory.
        container.put_archive(dest_dir, tar_buffer.read())
        logger.debug(f"[{container.short_id}] File written to {dest_path}")

    await asyncio.to_thread(_copy)


async def execute(
    container,
    command: str,
    timeout: int | None = None,
    user: str = "sandbox",
) -> ExecResult:
    """
    Run `command` inside the container.
    Returns ExecResult with stdout, stderr, exit_code, duration_ms.
    Kills container after `timeout` seconds if it hangs.
    """
    timeout = timeout or settings.container_timeout_seconds
    start = time.monotonic()

    def _exec():
        result = container.exec_run(
            cmd=["bash", "-c", command],
            stdout=True,
            stderr=True,
            demux=True,          # separate stdout/stderr streams
            user=user,
        )
        stdout_bytes, stderr_bytes = result.output or (b"", b"")
        return (
            (stdout_bytes or b"").decode("utf-8", errors="replace"),
            (stderr_bytes or b"").decode("utf-8", errors="replace"),
            result.exit_code or 0,
        )

    try:
        stdout, stderr, exit_code = await asyncio.wait_for(
            asyncio.to_thread(_exec),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(f"[{container.short_id}] Command timed out after {timeout}s: {command}")
        if await is_alive(container):
            logger.info(f"[{container.short_id}] Container still alive after timeout - keeping it running for next command")
            return ExecResult(
                stdout="",
                stderr=f"[TIMEOUT] Command exceeded {timeout}s limit but container remains healthy.",
                exit_code=124,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        else:
            logger.warning(f"[{container.short_id}] Container is NOT alive after timeout - reporting as crash")
            return ExecResult(
                stdout="",
                stderr="[CRASH] The container stopped or died during command execution.",
                exit_code=137, # Standard Docker exit code for SIGKILL/Death
                duration_ms=int((time.monotonic() - start) * 1000),
            )
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        err_msg = f"Docker engine error: {exc}"
        logger.error(f"[{container.short_id}] {err_msg} (after {duration_ms}ms)")
        return ExecResult(
            stdout="",
            stderr=f"[SYSTEM_ERROR] {err_msg}",
            exit_code=500,  # Generic internal error code
            duration_ms=duration_ms,
        )

    duration_ms = int((time.monotonic() - start) * 1000)
    logger.debug(f"[{container.short_id}] exit={exit_code} | {duration_ms}ms | cmd: {command[:80]}")
    return ExecResult(stdout=stdout, stderr=stderr, exit_code=exit_code, duration_ms=duration_ms)


async def destroy(container) -> None:
    """Stop and remove the container. Always call this in a finally block."""
    def _destroy():
        try:
            container.stop(timeout=3)
        except Exception:
            pass
        try:
            container.remove(force=True)
            logger.info(f"Container destroyed: {container.short_id}")
        except NotFound:
            pass  # already gone
        except Exception as exc:
            logger.warning(f"Could not remove container {container.short_id}: {exc}")

    return await asyncio.to_thread(_destroy)



```

## api/services/sandbox/laravel.py
```python

import base64
import logging
import re
import shlex
from dataclasses import dataclass
from api.config import get_settings
from api.services.sandbox import docker

logger = logging.getLogger(__name__)
settings = get_settings()

@dataclass
class ClassInfo:
    """Metadata for the PHP class being repaired."""
    namespace: str
    clean_namespace: str
    classname: str
    dest_file: str
    fqcn: str
    route_resource: str

async def detect_class_info(container) -> ClassInfo:
    """Detect namespace and classname from /submitted/code.php."""
    # Pre-lint to ensure valid detection
    await docker.execute(container, "php -l /submitted/code.php", timeout=5)

    ns_cmd = "php -r '$c=@file_get_contents(\"/submitted/code.php\"); if(preg_match(\"/namespace\\s+([^;\\s]+)/\",$c,$m)) echo trim($m[1]);'"
    cls_cmd = "php -r '$c=@file_get_contents(\"/submitted/code.php\"); if(preg_match(\"/class\\s+(\\w+)/\",$c,$m)) echo $m[1];'"
    
    ns_res = await docker.execute(container, ns_cmd, timeout=5)
    cls_res = await docker.execute(container, cls_cmd, timeout=5)
    
    namespace = ns_res.stdout.strip().replace("\\\\", "\\").replace("\\", "/") or "App/Http/Controllers"
    classname = cls_res.stdout.strip() or "SubmittedClass"
    
    clean_ns = namespace.replace("/", "\\").strip("\\")
    import posixpath
    dest_path = ("app/" + clean_ns[4:].replace("\\", "/")) if clean_ns.startswith("App\\") else clean_ns.replace("\\", "/")
    dest_file = posixpath.normpath(f"/var/www/sandbox/{dest_path}/{classname}.php")
    
    # Security Check: Prevent namespace path traversal
    if not dest_file.startswith("/var/www/sandbox/"):
        logger.warning(f"Malicious or invalid namespace detected: {namespace}. Falling back.")
        dest_file = f"/var/www/sandbox/app/Http/Controllers/{classname}.php"
    
    resource = re.sub(r'Controller$', '', classname, flags=re.IGNORECASE).lower()
    
    return ClassInfo(
        namespace=namespace,
        clean_namespace=clean_ns,
        classname=classname,
        dest_file=dest_file,
        fqcn=f"{clean_ns}\\{classname}",
        route_resource=f"{resource}s" if resource else f"{classname.lower()}s"
    )

async def setup_sqlite(container) -> None:
    """Configure container for internal SQLite usage and ensure base classes exist."""
    sh_script = """#!/bin/bash
# 1. Setup SQLite
touch /var/www/sandbox/database/database.sqlite
chmod 666 /var/www/sandbox/database/database.sqlite
sed -i 's/DB_CONNECTION=.*/DB_CONNECTION=sqlite/' /var/www/sandbox/.env
sed -i 's|DB_DATABASE=.*|DB_DATABASE=/var/www/sandbox/database/database.sqlite|' /var/www/sandbox/.env
php /var/www/sandbox/artisan migrate --force

# 2. Ensure base Controller exists (Laravel 11 might not have it)
mkdir -p /var/www/sandbox/app/Http/Controllers
if [ ! -f /var/www/sandbox/app/Http/Controllers/Controller.php ]; then
cat << 'EOF' > /var/www/sandbox/app/Http/Controllers/Controller.php
<?php
namespace App\Http\Controllers;
abstract class Controller { }
EOF
fi
"""
    await docker.copy_file(container, "/tmp/setup_sqlite.sh", sh_script)
    await docker.execute(container, "bash /tmp/setup_sqlite.sh", timeout=30, user="root")

async def place_code_in_laravel(container, info: ClassInfo) -> bool:
    """Inject code into the correct Laravel PSR-4 path and verify via Tinker."""
    dest_dir = shlex.quote(str(__import__('pathlib').Path(info.dest_file).parent))
    
    tinker_script = f"try {{ class_exists('{info.fqcn}') ? print('OK') : throw new Exception(); }} catch(Throwable $e) {{ print('ERR'); }}"
    b64_tinker = base64.b64encode(tinker_script.encode()).decode()
    
    cmd = (
        f"mkdir -p {dest_dir} && "
        f"cp /submitted/code.php {shlex.quote(info.dest_file)} && "
        f"cd /var/www/sandbox && php artisan optimize:clear >/dev/null && "
        f"composer dump-autoload -q && "
        f"php artisan tinker --execute=\"$(echo {b64_tinker} | base64 -d)\""
    )
    res = await docker.execute(container, cmd, timeout=settings.container_timeout_seconds)
    return "OK" in res.stdout and "ERR" not in res.stdout

async def scaffold_route(container, info: ClassInfo) -> None:
    """Idempotently register a resource route in api.php."""
    php_script = f"<?php $f='/var/www/sandbox/routes/api.php'; $c=file_get_contents($f); if(!str_contains($c,'{info.classname}::class')) file_put_contents($f,\"\\nRoute::apiResource('{info.route_resource}', \\\\{info.fqcn}::class);\\n\",FILE_APPEND);"
    await docker.copy_file(container, "/tmp/scaffold.php", php_script)
    await docker.execute(container, "php /tmp/scaffold.php && php /var/www/sandbox/artisan route:clear", timeout=10)

async def execute_code(container, code: str) -> dict:
    """Write and execute the provided PHP code in the sandbox using Tinker."""
    await docker.copy_code(container, code)
    
    # Use Tinker to execute the code so it's bootstrapped in the Laravel environment
    # We wrap it in a try-catch to get clean error output
    tinker_code = (
        "try { require '/submitted/code.php'; } "
        "catch (Throwable $e) { echo $e->getMessage() . ' in ' . $e->getFile() . ':' . $e->getLine() . \"\\n\" . $e->getTraceAsString(); exit(1); }"
    )
    b64_code = base64.b64encode(tinker_code.encode()).decode()
    
    res = await docker.execute(
        container, 
        f"cd /var/www/sandbox && php artisan tinker --execute=\"$(echo {b64_code} | base64 -d)\"", 
        timeout=15
    )
    
    return {
        "output": res.stdout, 
        "error": res.stderr if res.exit_code != 0 else (res.stdout if res.exit_code != 0 else None), 
        "exit_code": res.exit_code
    }

```

## api/services/boost_service.py
```python
"""
api/services/boost_service.py — Query Laravel Boost inside a running sandbox container.

Copilot addition: cache results by (framework_version, error_signature_hash)
to avoid redundant exec calls and reduce cost on repeated errors.
"""
import hashlib
import json
import logging
import shlex
from dataclasses import dataclass, field, asdict

from api.services.sandbox import docker as docker_service
import api.services.sandbox as sandbox

docker = docker_service

logger = logging.getLogger(__name__)

# Simple in-process cache: key -> BoostContext JSON string
_cache: dict[str, str] = {}


@dataclass
class BoostContext:
    schema_info: str = ""
    docs_excerpts: list[str] = field(default_factory=list)
    component_type: str = "unknown"

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def empty(cls) -> "BoostContext":
        return cls(
            schema_info="No schema info available.",
            docs_excerpts=[],
            component_type="unknown",
        )

    def to_prompt_text(self) -> str:
        parts = []
        if self.schema_info:
            parts.append(f"## Relevant Schema\n{self.schema_info}")
        if self.docs_excerpts:
            parts.append("## Laravel Docs Excerpts\n" + "\n---\n".join(self.docs_excerpts))
        if self.component_type and self.component_type != "unknown":
            parts.append(f"## Detected Component Type\n{self.component_type}")
        return "\n\n".join(parts) if parts else "No Boost context available."


def _cache_key(submission_id: str, error_text: str, framework_version: str = "laravel-12") -> str:
    """Cache by (submission_id, framework_version, error_signature_hash)."""
    sig = hashlib.sha256(f"{submission_id}:{framework_version}:{error_text[:500]}".encode()).hexdigest()
    return sig


async def get_boost_context(container_id: str, error_text: str, submission_id: str | None = None) -> str:
    """Compatibility wrapper used by the orchestrator and tests."""
    container = sandbox.get_container(container_id)
    return await query_context(container, error_text, submission_id=submission_id)


async def query_context(container_or_id, error_text: str, submission_id: str | None = None) -> str:
    """
    Query Boost inside the running container for schema + docs context.
    Returns a JSON string (stored in DB) and is also cached in-process.
    Gracefully falls back to empty context if Boost commands fail.
    """
    if isinstance(container_or_id, str):
        container = sandbox.get_container(container_or_id)
    else:
        container = container_or_id

    cache_key = _cache_key(submission_id or "unknown", error_text)
    if cache_key in _cache:
        logger.debug("[Boost] Cache hit")
        return _cache[cache_key]

    context = await _fetch_boost_context(container, error_text)
    result_json = context.to_json()
    _cache[cache_key] = result_json
    return result_json

async def _fetch_boost_context(container, error_text: str) -> BoostContext:
    """Run Boost artisan commands inside the container."""

    # 1. Get schema info — try boost:schema, fallback to model:show
    schema_result = await docker_service.execute(
        container,
        "php artisan boost:schema --format=text 2>&1",
        timeout=30,
    )
    schema_info = ""
    if schema_result.exit_code == 0:
        schema_info = schema_result.stdout.strip()
    else:
        # Fallback: list tables or show models if possible
        logger.debug("[Boost] boost:schema failed, trying native fallbacks")
        fallback = await docker_service.execute(container, "php artisan model:show --all 2>&1")
        if fallback.exit_code == 0:
            schema_info = fallback.stdout.strip()

    # 2. Get relevant docs excerpt — extract error type for query
    error_type = _extract_error_type(error_text)
    safe_query = shlex.quote(error_type)
    docs_result = await docker_service.execute(
        container,
        f"php artisan boost:docs --query={safe_query} --limit=3 2>&1",
        timeout=30,
    )
    docs_raw = ""
    if docs_result.exit_code == 0:
        docs_raw = docs_result.stdout.strip()
    else:
        # Fallback: just list routes to give some idea of the app structure
        fallback = await docker_service.execute(container, "php artisan route:list --except-vendor 2>&1")
        if fallback.exit_code == 0:
            docs_raw = f"Note: boost:docs unavailable. Current routes:\n{fallback.stdout.strip()}"
    docs_excerpts = [d.strip() for d in docs_raw.split("\n---\n") if d.strip()]

    # 3. Detect component type from error
    component_type = _detect_component_type(error_text)

    if not schema_info and not docs_excerpts:
        logger.warning("[Boost] Both commands returned empty — using fallback context")
        return BoostContext.empty()

    return BoostContext(
        schema_info=schema_info,
        docs_excerpts=docs_excerpts,
        component_type=component_type,
    )


def _extract_error_type(error_text: str) -> str:
    """Pull a short error type string for the Boost docs query."""
    lines = error_text.splitlines()
    for line in lines:
        line_lower = line.lower()
        if any(kw in line_lower for kw in ["error:", "exception:", "fatal"]):
            return line.strip()[:120]
    return error_text[:120]


def _detect_component_type(error_text: str) -> str:
    """Heuristic: detect what kind of Laravel component the error relates to."""
    text = error_text.lower()
    if "controller" in text:
        return "controller"
    if "model" in text or "eloquent" in text:
        return "model"
    if "migration" in text or "schema" in text:
        return "migration"
    if "middleware" in text:
        return "middleware"
    if "route" in text:
        return "route"
    if "request" in text or "validation" in text:
        return "form_request"
    return "unknown"

```

## docker/laravel-sandbox/Dockerfile
```bash
FROM php:8.3-cli-alpine

LABEL maintainer="Adamu Joseph Obinna"
LABEL description="Laravel 12 AI Repair Sandbox — PHP 8.3 + Boost + Pest (SQLite)"

# ── 1. Mirror Optimization ────────────────────────────────────────────────────
RUN sed -i 's/dl-cdn.alpinelinux.org/uk.alpinelinux.org/g' /etc/apk/repositories || true

# ── 2. System dependencies ────────────────────────────────────────────────────
RUN apk add --no-cache \
    bash \
    curl \
    git \
    unzip \
    icu-libs \
    libzip \
    libpng \
    libjpeg-turbo \
    libwebp \
    oniguruma \
    sqlite

# ── 3. Build dependencies + PHP extensions ────────────────────────────────────
# SQLite only — no pdo_mysql, no mysql-client needed
RUN apk add --no-cache --virtual .build-deps \
    $PHPIZE_DEPS \
    icu-dev \
    libzip-dev \
    libpng-dev \
    libjpeg-turbo-dev \
    libwebp-dev \
    oniguruma-dev \
    sqlite-dev \
    && docker-php-ext-configure gd --with-jpeg --with-webp \
    && docker-php-ext-install -j$(nproc) \
        pdo \
        pdo_sqlite \
        gd \
        bcmath \
        intl \
        mbstring \
        zip \
        pcntl \
    && apk del .build-deps

# ── 4. Redis + pcov PHP extensions ───────────────────────────────────────────
# redis — Laravel cache layer config compatibility
# pcov  — Pest mutation coverage (pest-plugin-mutate checks pcov.enabled at runtime)
RUN apk add --no-cache --virtual .build-deps $PHPIZE_DEPS \
    && MAKEFLAGS="-j$(nproc)" pecl install redis pcov \
    && docker-php-ext-enable redis pcov \
    && apk del .build-deps

# ── 4b. Activate pcov for mutation testing ────────────────────────────────────
# pest --mutate requires pcov.enabled=1 — installing the extension is not enough.
# Without this, every mutation run fails with "Extension pcov not found" regardless
# of whether pcov.so is loaded, making the mutation gate permanently soft-pass.
RUN echo "pcov.enabled=1" >> /usr/local/etc/php/conf.d/docker-php-ext-pcov.ini \
    && echo "pcov.directory=/var/www/sandbox/app" >> /usr/local/etc/php/conf.d/docker-php-ext-pcov.ini

# ── 5. Composer ───────────────────────────────────────────────────────────────
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer
ENV COMPOSER_ALLOW_SUPERUSER=1
ENV COMPOSER_NO_INTERACTION=1

WORKDIR /var/www

# ── 6. Create Laravel 12 project ─────────────────────────────────────────────
RUN composer create-project laravel/laravel sandbox "12.*" --prefer-dist --no-progress

WORKDIR /var/www/sandbox

# ── 7. Install Laravel packages ───────────────────────────────────────────────
RUN composer require predis/predis --no-progress && \
    composer require --dev \
        laravel/boost \
        "pestphp/pest:^3.0" \
        "pestphp/pest-plugin-laravel:^3.0" \
        "pestphp/pest-plugin-mutate:^3.0" \
        --with-all-dependencies \
        --no-progress

# ── 8. Initialise Pest ────────────────────────────────────────────────────────
RUN ./vendor/bin/pest --init

# ── 9. Setup API and Install Boost ──────────────────────────────────────────────
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    && php artisan install:api --force \
    && php artisan vendor:publish --tag=boost-config --force 2>/dev/null || true \
    && php artisan boost:install --skill=rest-api --skill=pest-api --force 2>/dev/null || true

# ── 10. Permissions & Optimization ────────────────────────────────────────────
RUN addgroup -S sandbox && adduser -S -G sandbox sandbox \
    && chown -R sandbox:sandbox /var/www/sandbox \
    && chmod -R 777 /var/www/sandbox/storage \
    && php artisan optimize 2>/dev/null || true

ENTRYPOINT ["/entrypoint.sh"]

```

## api/routers/repair.py
```python
"""
api/routers/repair.py — Core repair endpoints + SSE stream.

POST /api/repair              Submit code → 202 with submission_id
GET  /api/repair/{id}         Get full result + iterations
GET  /api/repair/{id}/stream  SSE stream of live repair progress
"""
import json
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from api.config import get_settings
from api.database import get_db
from api.models import Submission
from api.schemas import RepairRequest, RepairSubmitResponse, SubmissionOut
from api.services.repair import run_repair_loop

router = APIRouter(prefix="/api", tags=["repair"])
settings = get_settings()

# In-memory event queues per submission_id (for SSE)
# In production, replace with Redis pub/sub or database
_event_queues: dict[str, list[dict]] = {}
_repair_done: dict[str, bool] = {}


@router.post("/repair", response_model=RepairSubmitResponse, status_code=202)
async def submit_repair(
    request: RepairRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Submit PHP code for repair. Returns submission_id immediately."""
    # Validate code size
    if len(request.code.encode("utf-8")) > settings.max_code_size_kb * 1024:
        raise HTTPException(400, f"Code exceeds maximum size of {settings.max_code_size_kb}KB")

    # Create submission record
    submission_id = str(uuid.uuid4())
    submission = Submission(
        id=submission_id,
        created_at=datetime.now(timezone.utc),
        original_code=request.code,
        status="pending",
    )
    db.add(submission)
    await db.commit()

    # Set up event queue for SSE
    _event_queues[submission_id] = []
    _repair_done[submission_id] = False

    # Run repair loop as background task
    background_tasks.add_task(
        _run_repair_background,
        submission_id=submission_id,
        code=request.code,
        prompt=request.prompt,
        max_iterations=request.max_iterations,
        use_boost=request.use_boost,
        use_mutation_gate=request.use_mutation_gate,
    )

    return RepairSubmitResponse(submission_id=submission_id)


async def _run_repair_background(
    submission_id: str,
    code: str,
    prompt: str | None,
    max_iterations: int | None,
    use_boost: bool,
    use_mutation_gate: bool,
) -> None:
    """Background task: runs the repair loop and pushes events to the SSE queue."""
    from api.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        async for event in run_repair_loop(
            submission_id=submission_id,
            code=code,
            prompt=prompt,
            db=db,
            max_iterations=max_iterations,
            use_boost=use_boost,
            use_mutation_gate=use_mutation_gate,
        ):
            _event_queues.setdefault(submission_id, []).append(event)
    _repair_done[submission_id] = True


@router.get("/repair/{submission_id}/stream")
async def stream_repair(submission_id: str, db: AsyncSession = Depends(get_db)):
    """
    SSE endpoint — streams live repair events.
    Connect with: new EventSource('/api/repair/<id>/stream')
    """
    submission = await db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(404, f"Submission {submission_id} not found")

    async def event_generator() -> AsyncGenerator[str, None]:
        import asyncio
        sent_idx = 0
        while True:
            queue = _event_queues.get(submission_id, [])
            while sent_idx < len(queue):
                evt = queue[sent_idx]
                yield f"data: {json.dumps(evt)}\n\n"
                sent_idx += 1

            if _repair_done.get(submission_id, False) and sent_idx >= len(queue):
                break
            await asyncio.sleep(0.2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/repair/{submission_id}", response_model=SubmissionOut)
async def get_repair_status(submission_id: str, db: AsyncSession = Depends(get_db)):
    """Get the current status and all iteration details for a submission."""
    result = await db.execute(
        select(Submission)
        .where(Submission.id == submission_id)
        .options(selectinload(Submission.iterations))
    )
    submission = result.scalar_one_or_none()
    if not submission:
        raise HTTPException(404, f"Submission {submission_id} not found")
    return submission

```

## api/main.py
```python
"""
api/main.py — FastAPI application entry point.

Start with:
    uvicorn api.main:app --reload --port 8000
"""
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from api.limiter import limiter

from api.config import get_settings
from api.database import create_tables
from api.routers.health import router as health_router
from api.routers.repair import router as repair_router
from api.routers.history import router as history_router
from api.routers.evaluate import router as evaluate_router
from api.routers.stats import router as stats_router
from api.routers.admin import router as admin_router
from api.logging_config import setup_logging
from api.broker import broker
from api.redis_client import close_redis

settings = get_settings()

# Initialize unified logging (Console + File)
setup_logging(debug=settings.debug)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup/shutdown tasks."""
    logger.info("Starting up — creating DB tables if needed...")
    try:
        await create_tables()
        logger.info("DB ready.")
        await broker.startup()
        logger.info("TaskIQ broker started.")
    except Exception as exc:
        logger.critical(f"Database initialization failed: {exc}", exc_info=True)
        print(f"FATAL: Could not initialize database: {exc}", file=sys.stderr)
        sys.exit(1)
    yield
    await broker.shutdown()
    await close_redis()
    logger.info("Shutting down — goodbye.")

app = FastAPI(
    title="Laravel AI Repair Platform",
    description=(
        "Submit broken PHP/Laravel REST API code, watch it get repaired "
        "iteratively via LLM + Laravel Boost context, validated with Pest + mutation testing."
    ),
    version="0.1.0",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(repair_router)
app.include_router(history_router)
app.include_router(evaluate_router)
app.include_router(stats_router)
app.include_router(admin_router)


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Laravel AI Repair Platform — see /docs"}

```

## api/config.py
```python
"""
api/config.py — Application settings loaded from .env via Pydantic Settings.
All config is centralised here. Never read env vars directly anywhere else.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
import sys


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Security ─────────────────────────────────────────────────────────────
    # Master token for simple "Option A" authentication
    master_repair_token: str = "change-me-in-production"
    jwt_secret_key: str = "super-secret-key-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 1 day

    # ── AI Provider ──────────────────────────────────────────────────────────
    # Free providers (recommended)
    dashscope_api_key: str = ""              # bailian.console.aliyun.com — 1M free tokens
    cerebras_api_key: str = ""               # cloud.cerebras.ai — blazing fast
    gemini_api_key: str = ""                 # aistudio.google.com — free (rate-limited)
    groq_api_key: str = ""                   # console.groq.com — free tier
    nvidia_api_key: str = ""                 # build.nvidia.com — strong & safe picks
    deepseek_api_key: str = ""              # platform.deepseek.com — near-free
    ollama_base_url: str = "http://localhost:11434"  # local, no key needed
    # Paid providers
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    # Active provider: fallback | qwen | cerebras | gemini | groq | deepseek | ollama | anthropic | openai
    default_ai_provider: str = "fallback"
    ai_model: str = "nvidia_nim/meta/llama-3.3-70b-instruct"
    ai_temperature: float = 0.0              # deterministic for reproducibility

    # ── Docker ───────────────────────────────────────────────────────────────
    docker_image_name: str = "laravel-sandbox:latest"
    docker_network: str = "repair-net"
    container_memory_limit: str = "512m"
    container_cpu_limit: float = 0.5
    container_pid_limit: int = 256            # tinker + composer need many child processes
    container_timeout_seconds: int = 180      # WSL filesystem is slow for composer ops
    max_iterations: int = 4

    # ── App ───────────────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./data/repair.db"
    redis_url: str = "redis://localhost:6379/0"
    max_code_size_kb: int = 100
    secret_key: str = "change-this-in-production"
    debug: bool = False

    # ── Mutation Gate ─────────────────────────────────────────────────────────
    mutation_score_threshold: int = 80       # pest --mutate must score >= this %
    mutation_timeout_seconds: int = 120      # timeout for pest --mutate

    # ── Role Pipeline ─────────────────────────────────────────────────────────
    # Set USE_ROLE_PIPELINE=true in .env to activate the 4-role
    # Planner → Verifier → Executor → Reviewer cycle.
    # When false, the system falls back to the single get_repair() call (legacy mode).
    use_role_pipeline: bool = False


def _validate_settings(s: Settings) -> None:
    """Ensure critical security values have been changed from defaults."""
    if s.master_repair_token == "change-me-in-production":
        print("ERROR: MASTER_REPAIR_TOKEN is still set to the default. Change it in .env.", file=sys.stderr)
        sys.exit(1)


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — call this everywhere instead of instantiating Settings()."""
    settings = Settings()
    _validate_settings(settings)
    return settings

```

## api/models.py
```python
"""
api/models.py — SQLAlchemy ORM models for the repair platform.

Two tables:
  - Submission: one row per user code submission
  - Iteration:  one row per repair loop iteration
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        Index("idx_submissions_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    original_code: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending | running | success | failed
    total_iterations: Mapped[int] = mapped_column(Integer, default=0)
    final_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Research Metadata
    case_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    experiment_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    iterations: Mapped[list["Iteration"]] = relationship(
        "Iteration", back_populates="submission", cascade="all, delete-orphan"
    )


class Iteration(Base):
    __tablename__ = "iterations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    submission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("submissions.id"), nullable=False
    )
    iteration_num: Mapped[int] = mapped_column(Integer, nullable=False)
    code_input: Mapped[str] = mapped_column(Text, nullable=False)
    execution_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_logs: Mapped[str | None] = mapped_column(Text, nullable=True)
    boost_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)  # legacy single-model field
    # Role pipeline model tracking (populated when USE_ROLE_PIPELINE=true)
    planner_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    executor_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reviewer_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    patch_applied: Mapped[str | None] = mapped_column(Text, nullable=True)
    pest_test_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    pest_test_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    mutation_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    submission: Mapped["Submission"] = relationship("Submission", back_populates="iterations")


class RepairSummary(Base):
    """
    Stores successful repairs (Phase 7).
    When a future defect exhibits the same error_type, we retrieve
    relevant summaries to show the AI how this error was fixed before.
    """
    __tablename__ = "repair_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    error_type: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    diagnosis: Mapped[str] = mapped_column(Text, nullable=False)
    fix_applied: Mapped[str] = mapped_column(Text, nullable=False)
    what_did_not_work: Mapped[str | None] = mapped_column(Text, nullable=True)
    iterations_needed: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

```

## MANUAL.md
```md
# Laravel AI Repair Platform — Comprehensive Technical Manual

**Author:** Adamu Joseph Obinna
**Version:** 1.0 — BSc Thesis 2026
**Stack:** FastAPI · Python 3.12 · Docker · Laravel 12 · Pest 3 · Laravel Boost · SQLite · Vanilla JS

---

## Table of Contents

1. [What This Platform Does](#1-what-this-platform-does)
2. [System Architecture](#2-system-architecture)
3. [The 7-Step Iterative Repair Loop](#3-the-7-step-iterative-repair-loop)
4. [Directory Structure & File Reference](#4-directory-structure--file-reference)
5. [Setting Up & Running (WSL Ubuntu)](#5-setting-up--running-wsl-ubuntu)
6. [Environment Variables Reference](#6-environment-variables-reference)
7. [AI Provider Configuration](#7-ai-provider-configuration)
8. [API Reference](#8-api-reference)
9. [Frontend UI Walkthrough](#9-frontend-ui-walkthrough)
10. [Docker Sandbox Explained](#10-docker-sandbox-explained)
11. [Services Deep-Dive](#11-services-deep-dive)
12. [Database Schema](#12-database-schema)
13. [Testing Guide](#13-testing-guide)
14. [MCP Integration (Cursor / Claude Code)](#14-mcp-integration-cursor--claude-code)
15. [Security Model](#15-security-model)
16. [Thesis Batch Evaluation](#16-thesis-batch-evaluation)
17. [Troubleshooting](#17-troubleshooting)

---

## 1. What This Platform Does

The **Laravel AI Repair Platform** automatically fixes broken AI-generated PHP/Laravel REST API code using an iterative loop of:

- **Docker container execution** (safe, isolated)
- **Laravel Boost context enrichment** (live schema + docs)
- **LLM-powered repair** (Claude, Gemini, GPT, Groq, DeepSeek, Ollama)
- **Pest test generation** (validates the fix works)
- **Mutation testing gate** (`pest --mutate ≥ 80%` — ensures the fix is robust)

It repeats up to **4 times** (configurable via `MAX_ITERATIONS` env var) until the code is clean, or reports failure.

### Core Mechanic in One Diagram

![System Architecture](C:\Users\ESTHER\.gemini\antigravity\brain\42fcb583-c7f5-4f26-950b-54824fad965d\architecture_diagram_1775660355152.png)

---

## 2. System Architecture

The platform operates as a multi-tier web application orchestration engine:

| Tier | Technology | Location |
|------|-----------|----------|
| **Frontend** | React 19 + TypeScript + Tailwind 4 | `laravibe-fe/` |
| **Coordinator API** | FastAPI Python 3.12 (asyncio) | `api/` |
| **Sandbox Runtime** | Docker container (PHP 8.3 + Laravel 12) | `docker/laravel-sandbox/` |
| **AI Providers** | Claude / Gemini / GPT / Groq / DeepSeek / Ollama | External / Local |

### Data Flow

```
Browser
  │  POST /api/repair  (broken code)
  ▼
FastAPI (repair.py router)
  │  Creates Submission record in SQLite
  │  Starts background task
  ▼
repair_service.run_repair_loop()
  │
  ├─ docker_service.create_container()  → isolated container spawned
  ├─ docker_service.copy_code()         → code.php copied in via tar archive
  ├─ docker_service.execute()           → PHP lint → artisan tinker validation
  │
  ├─ [if error] boost_service.query_context()   → php artisan boost:schema/docs inside container
  ├─ [if error] ai_service.get_repair()         → LLM call with full prompt + context
  ├─ [if error] patch_service.apply()           → diff applied to code string
  │
  ├─ [if success] Pest test run
  ├─ [if pest OK] pest --mutate  (mutation gate)
  │
  └─ SSE events streamed back → Browser updates panels live
```

The browser connects to `GET /api/repair/{id}/stream` via `EventSource` (Server-Sent Events) and receives real-time JSON events as the loop runs.

---

## 3. The 13-Step Iterative Repair Loop

### Design Change: Single Persistent Container (V2)

The container is created **once before the loop** and destroyed in `finally`. It persists across all iterations — files created by `create_file` patches in iteration N are naturally present in iteration N+1. No re-injection needed.

### Step-by-Step Breakdown

Each iteration (up to `MAX_ITERATIONS`, default 4) follows this exact sequence in [`api/services/repair_service.py`](api/services/repair_service.py):

#### Step 1 — Copy Code
The current code string is written to `/submitted/code.php` via in-memory tar archive.

#### Step 2 — PHP Lint Gate
`php -l /submitted/code.php` — fastest syntax check. Fails immediately on syntax errors without entering Laravel.

#### Step 3 — Detect Class Info
`sandbox_service.detect_class_info()` parses namespace and classname via PHP one-liners, builds `ClassInfo` (FQCN, PSR-4 destination path, route resource name).

#### Step 4 — Place Code in Laravel
`sandbox_service.place_code_in_laravel()` copies to the PSR-4 path, runs `composer dump-autoload`, validates via Tinker. `CLASS_OK` sentinel confirms success.

#### Step 5 — Scaffold Route (BEFORE Boost)
`sandbox_service.scaffold_route()` appends `Route::apiResource()` to `routes/api.php` idempotently. Runs **before** Boost so `route:list` sees the new route in the context it feeds to the AI.

#### Step 6 — Zoom-In Discovery
`discovery.py` scans `use` statements and uses `artisan tinker` reflection to fetch public method signatures for referenced classes.

#### Step 7 — Query Boost Context
`boost_service.query_context()` runs inside the container (schema + docs).

#### Step 8 — Retrieve Similar Past Repairs
`context_service.retrieve_similar_repairs()` scores the 200-item sliding window.

#### Step 9 — Post-Mortem Strategy
If a previous iteration failed, the **Critic** analyzes logs and generates a `Fix Strategy` JSON.

#### Step 10 — Call AI
`ai_service.get_repair()` assembles the prompt (including discovery metadata and post-mortem strategy).

#### Step 10 — Ensure `covers()` Directive
`sandbox_service.ensure_covers_directive()` injects missing `use function Pest\Laravel\{...};` imports and a `covers(ClassName::class);` directive into the AI-generated test.

#### Step 11 — Apply Patches
`patch_service.apply_all()` processes the `patches` list:

| Action | What Happens |
|--------|-------------|
| `full_replace` | Replaces entire submitted file content |
| `create_file` | New file written to container + `composer dump-autoload` + `php artisan migrate` |
| `replace` / `append` | **Banned** — raises `PatchApplicationError` immediately |

Forbidden filenames (`routes/api.php` etc.) are blocked silently.

#### Step 12 — Run Pest Test
System baseline test (`getJson('/api/{resource}')->assertSuccessful()`) runs first. On failure, `capture_laravel_log()` fetches the last 40 lines of Laravel's log to surface the real PHP exception.

#### Step 13 — Run Mutation Gate
Only runs if an AI-generated test is present. Test is linted first (`php -l`). Then `./vendor/bin/pest --mutate`. Score classified as: `covers_missing` → fail, `dependency_failure` → fail, `infra_failure` → soft-pass, real score → compare to threshold.

#### Iteration Result
Each iteration saved as an `Iteration` row (including partial `mutation_score` even on fails). SSE `complete` event emitted on success or exhaustion.

---

## 4. Directory Structure & File Reference

```
repair-platform/
│
├── api/                            ← FastAPI Python backend
│   ├── __init__.py
│   ├── main.py                     ← App entry point, lifespan, middleware
│   ├── config.py                   ← All settings via pydantic-settings (.env)
│   ├── database.py                 ← Async SQLAlchemy engine + get_db() dependency
│   ├── models.py                   ← ORM: Submission, Iteration tables
│   ├── schemas.py                  ← Pydantic v2 request/response models
│   │
│   ├── logging_config.py            ← Unified console + rotating file handler (10 MB × 5 backups)
│   ├── limiter.py                  ← slowapi rate limiter instance
│   ├── prompts/
│   │   └── repair_prompt.md        ← Main LLM repair prompt template (Spatie guidelines included)
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── health.py               ← GET /api/health
│   │   ├── repair.py               ← POST /api/repair, GET /api/repair/{id}, SSE stream
│   │   ├── history.py              ← GET /api/history
│   │   ├── evaluate.py             ← POST /api/evaluate (batch runs)
│   │   ├── stats.py                ← GET /api/stats (aggregate statistics)
│   │   └── admin.py                ← DELETE /api/admin/submissions/{id}
│   │
│   └── services/
│       ├── __init__.py
│       ├── docker_service.py       ← Container lifecycle (create/copy/exec/destroy/ping)
│       ├── sandbox_service.py      ← Laravel helpers (detect class, place code, Pest/mutate, covers)
│       ├── boost_service.py        ← Boost artisan commands + score-based component detection + caching
│       ├── ai_service.py           ← LLM routing (ROTATION_CHAIN + FALLBACK_CHAIN, 9 providers)
│       ├── patch_service.py        ← Patch application (full_replace/create_file; replace/append banned)
│       ├── escalation_service.py   ← 4-rule stuck loop detection + corrective prompt injection
│       ├── context_service.py      ← 200-item sliding window memory (store + retrieve similar repairs)
│       ├── evaluation_service.py   ← Batch evaluation orchestrator
│       ├── auth_service.py         ← Bearer token validation
│       └── repair_service.py       ← Main orchestration loop (413 lines)
│
├── docker/
│   ├── .dockerignore
│   └── laravel-sandbox/
│       ├── Dockerfile              ← PHP 8.3-alpine + Laravel 12 + Pest 3 + Laravel Boost
│       ├── docker-compose.yml      ← Optional compose for running the full stack
│       ├── entrypoint.sh           ← Container startup script
│       └── php.ini                 ← PHP config for the sandbox
│
├── frontend/
│   ├── index.html                  ← Single-page app layout (3-panel + sidebar)
│   ├── style.css                   ← Dark theme, panel layout, animations
│   └── app.js                      ← CodeMirror 5, SSE handling, diff2html, API calls
│
├── mcp/
│   └── server.py                   ← MCP JSON-RPC server (stdio transport)
│
├── scripts/
│   ├── dump_last_log.py            ← Debug utility: print last iteration logs from DB
│   └── run_case.sh                 ← Run a single evaluation case from batch manifest
│
├── tests/
│   ├── conftest.py                 ← Shared pytest fixtures (mock containers, PHP code)
│   ├── test_ai_service.py          ← Unit tests for LLM JSON parsing + prompt building
│   ├── test_boost_service.py       ← Unit tests for Boost context fetching + caching
│   ├── test_patch_service.py       ← Unit tests for all three patch actions
│   ├── test_repair_service.py      ← Unit tests for the repair loop state machine
│   ├── fixtures/
│   │   ├── missing_model.php       ← Broken: references App\Models\Product (doesn't exist)
│   │   ├── wrong_namespace.php     ← Broken: controller namespace doesn't match file path
│   │   └── missing_import.php     ← Broken: uses Str:: without importing the facade
│   └── integration/
│       └── test_full_repair.py     ← End-to-end tests (requires Docker + API key)
│
├── data/                           ← SQLite database lives here (auto-created)
├── venv/                           ← Python virtual environment (gitignored)
├── .env                            ← Secret keys (gitignored)
├── .env.example                    ← Template for .env
├── .gitignore
├── batch_manifest.yaml             ← Thesis evaluation configuration
├── pytest.ini                      ← Pytest config (asyncio_mode=auto)
├── requirements.txt                ← Python dependencies
├── start.sh                        ← WSL one-shot setup + launch script
└── PROJECT_MANUAL.md               ← Architecture overview (shorter version)
```

---

## 5. Setting Up & Running (WSL Ubuntu)

All Python dependencies are installed in WSL Ubuntu. Follow these steps exactly.

### Prerequisites

| Requirement | Check Command | Notes |
|------------|--------------|-------|
| Python 3.12+ | `python3 --version` | Must be 3.12+ |
| pip | `pip3 --version` | Comes with Python |
| Docker Desktop | `docker --version` | Enable WSL2 integration in Docker Desktop settings |
| At least one AI API key | — | Gemini is free at aistudio.google.com |

### Quickstart (One Command)

```bash
# Open WSL terminal, navigate to project, run:
bash start.sh
```

The `start.sh` script handles everything:
1. Creates Python virtual environment (`venv/`)
2. Installs all Python dependencies from `requirements.txt`
3. Copies `.env.example` → `.env` if `.env` doesn't exist
4. Checks Docker daemon is reachable
5. Builds the `laravel-sandbox:latest` Docker image (first time: ~5 minutes)
6. Runs unit tests
7. Starts the FastAPI server on `http://localhost:8000`

### Manual Setup (Step by Step)

```bash
# 1. Clone and enter (WSL path format)
cd "/mnt/c/Users/ESTHER/Desktop/Joseph's Project/laravel-ai-proj/repair-platform"

# 2. Create + activate venv
python3 -m venv venv
source venv/bin/activate

# 3. Install deps
pip install -r requirements.txt

# 4. Copy env and fill in your AI key
cp .env.example .env
nano .env   # Set GEMINI_API_KEY or another provider

# 5. Build the Docker sandbox image (once, ~5 min)
docker build -t laravel-sandbox:latest ./docker/laravel-sandbox/

# 6. Verify the image
docker run --rm laravel-sandbox:latest php -v
docker run --rm laravel-sandbox:latest php artisan --version
docker run --rm laravel-sandbox:latest ./vendor/bin/pest --version

# 7. Start the API
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# 8. Open the UI
# Open frontend/index.html in your browser
# OR visit http://localhost:8000/docs for the Swagger UI
```

### Accessing from Windows Browser

Since the server binds to `0.0.0.0`, you can open the frontend directly in your Windows browser:

- Open `frontend/index.html` as a file (double-click)  
- API: `http://localhost:8000`  
- Swagger docs: `http://localhost:8000/docs`  
- Health check: `http://localhost:8000/api/health`

---

## 6. Environment Variables Reference

All settings live in `.env` and are loaded by `api/config.py` via `pydantic-settings`.

### AI Provider Keys

| Variable | Description | Get It |
|---------|-------------|--------|
| `GEMINI_API_KEY` | Google Gemini (recommended — free) | [aistudio.google.com](https://aistudio.google.com/app/apikey) |
| `GROQ_API_KEY` | Groq — free tier, fast | [console.groq.com](https://console.groq.com) |
| `DEEPSEEK_API_KEY` | DeepSeek — near-free, best code model | [platform.deepseek.com](https://platform.deepseek.com) |
| `ANTHROPIC_API_KEY` | Anthropic Claude — paid | [console.anthropic.com](https://console.anthropic.com) |
| `OPENAI_API_KEY` | OpenAI GPT — paid | [platform.openai.com](https://platform.openai.com) |
| `OLLAMA_BASE_URL` | Ollama local — no key needed | Default: `http://localhost:11434` |

### Active Provider Selection

```env
DEFAULT_AI_PROVIDER=gemini      # gemini | groq | deepseek | ollama | anthropic | openai
AI_MODEL=gemini-2.5-flash       # model name for the chosen provider
AI_TEMPERATURE=0.0              # always 0.0 for deterministic output
```

### Docker Settings

```env
DOCKER_IMAGE_NAME=laravel-sandbox:latest
CONTAINER_MEMORY_LIMIT=512m
CONTAINER_CPU_LIMIT=0.5
CONTAINER_PID_LIMIT=64
CONTAINER_TIMEOUT_SECONDS=90
MAX_ITERATIONS=4
```

> **Note:** `CONTAINER_TIMEOUT_SECONDS` governs general exec calls. The mutation test timeout is hardcoded at 120 s in `sandbox_service.py` and is not yet controlled by this setting.

### App Settings

```env
DATABASE_URL=sqlite+aiosqlite:///./data/repair.db
MAX_CODE_SIZE_KB=100
REPAIR_TOKEN=change-me-in-production
DEBUG=false
MUTATION_SCORE_THRESHOLD=80
```

> **`DEFAULT_AI_PROVIDER=fallback`** — uses `FALLBACK_CHAIN` for single submissions. During batch evaluation, `ROTATION_CHAIN` in `ai_service.py` overrides this entirely per iteration.

> [!IMPORTANT]
> Never commit `.env` — it is in `.gitignore`. Only `.env.example` (with placeholder values) is tracked by git.

---

## 7. AI Provider Configuration

The platform supports 6 AI backends. Switch by changing `DEFAULT_AI_PROVIDER` in `.env`.

### Recommended: Gemini (Free)

```env
DEFAULT_AI_PROVIDER=gemini
GEMINI_API_KEY=AIza...
AI_MODEL=gemini-2.5-flash
```

Gemini uses Google's OpenAI-compatible endpoint at `generativelanguage.googleapis.com/v1beta/openai/`. No extra SDK needed — the `openai` Python package handles it.

### Fast & Free: Groq

```env
DEFAULT_AI_PROVIDER=groq
GROQ_API_KEY=gsk_...
AI_MODEL=llama-3.3-70b-versatile
```

Groq hits `api.groq.com/openai/v1` — also OpenAI-compatible.

### Best Code Quality: DeepSeek

```env
DEFAULT_AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-...
AI_MODEL=deepseek-coder
```

### Fully Offline: Ollama

```bash
# Install Ollama then pull a model
ollama pull qwen2.5-coder:7b
```

```env
DEFAULT_AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
AI_MODEL=qwen2.5-coder:7b
```

Ollama requires at least 8GB RAM. Useful for air-gapped environments.

### Model Routing Table

| Provider | `DEFAULT_AI_PROVIDER` | Recommended `AI_MODEL` |
|---------|----------------------|------------------------|
| Nvidia NIM | `nvidia` | `Qwen/Qwen2.5-Coder-32B-Instruct` |
| Dashscope (Alibaba) | `dashscope` | `deepseek-v3` |
| Groq | `groq` | `llama-3.3-70b-versatile` |
| Cerebras | `cerebras` | `llama-3.3-70b` |
| Google Gemini | `gemini` | `gemini-2.5-flash` |
| DeepSeek | `deepseek` | `deepseek-coder` |
| Ollama | `ollama` | `qwen2.5-coder:7b` |
| Anthropic | `anthropic` | `claude-sonnet-4-6` |
| OpenAI | `openai` | `gpt-4o` |

### Batch Evaluation: ROTATION_CHAIN

During batch runs, `ROTATION_CHAIN` overrides `DEFAULT_AI_PROVIDER` per iteration:

| Iteration | Provider | Model |
|---|---|---|
| 0 | nvidia | `Qwen/Qwen2.5-Coder-32B-Instruct` |
| 1 | dashscope | `deepseek-v3` |
| 2 | nvidia | `meta/llama-3.3-70b-instruct` |
| 3 | gemini | `gemini-2.5-flash` |

---

## 8. API Reference

Base URL: `http://localhost:8000`

Interactive docs: `http://localhost:8000/docs`

### `GET /api/health`

Returns status of all connected services.

**Response:**
```json
{
  "status": "ok",
  "docker": "connected",
  "ai": "key_set",
  "db": "connected"
}
```

---

### `POST /api/repair`

Submit broken PHP/Laravel code for repair.

**Request body:**
```json
{
  "code": "<?php\nnamespace App\\Http\\Controllers\\Api;\n...",
  "max_iterations": 7
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `code` | string | ✅ | Must not be empty. Max `MAX_CODE_SIZE_KB` KB |
| `max_iterations` | int | ❌ | 1–10, defaults to `MAX_ITERATIONS` env var |

**Response (202 Accepted):**
```json
{
  "submission_id": "3a1b2c4d-...",
  "status": "pending",
  "message": "Repair queued. Connect to the stream endpoint for live progress."
}
```

Repair runs as a **background task** — the 202 response is immediate.

---

### `GET /api/repair/{submission_id}/stream`

Server-Sent Events (SSE) stream. Connect with `EventSource` in JS.

Each event is a JSON object:
```
data: {"event": "log_line", "data": {"msg": "Spinning up sandbox container..."}}

data: {"event": "iteration_start", "data": {"iteration": 1, "max": 7}}

data: {"event": "boost_queried", "data": {"schema": true, "component_type": "model"}}

data: {"event": "ai_thinking", "data": {"diagnosis": "...", "fix_description": "..."}}

data: {"event": "pest_result", "data": {"status": "pass", "output": "..."}}

data: {"event": "mutation_result", "data": {"score": 85.0, "threshold": 80, "passed": true}}

data: {"event": "patch_applied", "data": {"action": "replace", "fix": "Added missing import"}}

data: {"event": "complete", "data": {"status": "success", "final_code": "...", "iterations": 2, "mutation_score": 85.0}}
```

### SSE Event Reference

| Event | Emitted When |
|-------|-------------|
| `iteration_start` | Each loop iteration begins |
| `log_line` | Info/status message |
| `boost_queried` | Laravel Boost context retrieved |
| `ai_thinking` | LLM has returned a diagnosis and fix |
| `pest_result` | Pest tests have run |
| `mutation_result` | Mutation testing gate result |
| `patch_applied` | A patch was successfully applied |
| `error` | Non-fatal error (loop continues if possible) |
| `complete` | Loop finished (success or failed) |

---

### `GET /api/repair/{submission_id}`

Get the full result including all iteration details.

**Response:**
```json
{
  "id": "3a1b2c4d-...",
  "status": "success",
  "created_at": "2026-04-08T14:00:00Z",
  "total_iterations": 2,
  "final_code": "<?php\n...",
  "error_summary": null,
  "iterations": [
    {
      "id": "...",
      "iteration_num": 0,
      "status": "failed",
      "error_logs": "Fatal error: Class not found...",
      "patch_applied": "...",
      "pest_test_result": null,
      "mutation_score": null,
      "duration_ms": 4200,
      "created_at": "..."
    }
  ]
}
```

---

### `GET /api/history`

Returns the 50 most recent submissions (without iteration details).

---

### `POST /api/evaluate`

Runs the full batch evaluation suite defined in `batch_manifest.yaml`. Used for thesis experiments.

---

## 9. Frontend Deep-Dive (`laravibe-fe/`)

The frontend is a modern SPA designed for real-time observability and high-density data visualization, moving far beyond traditional static HTML to a dynamic URL-driven shell.

### 9.1 Technology Stack
- **Framework**: React 19 with TypeScript.
- **Build Tool**: Vite 6.
- **Styling**: Tailwind CSS 4.0 with `@tailwindcss/vite` plugin.
- **Routing**: React Router 7 (URL-driven navigation ensures deep-linked history mapping perfectly to `Submission` UUIDs).
- **Icons & Components**: Lucide React icons, framer-motion (optional micro-animations).

### 9.2 Design System: "Glass-Industrial"
The platform features an Anthropic-inspired aesthetic intended for professional research environments:
- **Surface Layering**: Hierarchical transparency (`surface-container-low/high/lowest`) simulating depth without relying on heavy shadows.
- **Typography**: Extensive use of monospaced and modern sans-serif fonts for code-centric observability.
- **Interaction HUD**: Hover-triggered accents and pulsing status indicators for the repair loop.

### 9.3 Live Streaming Engine (SSE)
The `RepairView` component utilizes an `EventSource` to visualize the backend workflow. The frontend state engine maps incoming backend SSE events to a linear UI progression:
`SPINNING` → `BOOSTING` → `THINKING` → `PATCHING` → `TESTING` → `MUTATING` → `COMPLETE`.

It gracefully parses `data: {"event": "log_line", ...}` updates, appending them to a virtualized log scroller.

---

## 10. DevOps & Sandbox Orchestration

The platform employs a strictly isolated runtime model to ensure security and execution determinism.

### 10.1 Sandbox Build Architecture (`laravel-sandbox:latest`)
Built from `docker/laravel-sandbox/Dockerfile`, the image outputs a production-grade Alpine 3.20 + PHP 8.3 environment preloaded with Laravel 12 and Pest 3. 

The build pipeline:
1. Installs Alpine system packages.
2. Compiles Redis and `pcov` (for mutation testing coverage) via parallelized `pecl`.
3. Bootstraps `composer create-project laravel/laravel sandbox "12.*"`.
4. Installs Laravel Pest, Boost, and Sanctum packages.

### 10.2 Automated Environment Setup (`start.sh`)
The `start.sh` utility orchestrates the entire DevOps lifecycle for local development:
1. **Venv Management**: Automates Python 3.12 environment creation and package synchronization.
2. **Secret Management**: Validates `.env` and `SECRET_KEY` presence.
3. **Image Logic**: Checks for `laravel-sandbox:latest` and performs a clean build if missing.
4. **Daemon Assessment**: Validates the Docker daemon is accessible via WSL2 integration.

### 10.3 Container Security Constraints
Each code execution runs within a tightly bounded lifecycle:

```python
client.containers.run(
    image="laravel-sandbox:latest",
    network_mode="none",                    # Zero internet access
    mem_limit="512m",                       # Memory cap restricts OOM payloads
    nano_cpus=int(0.5 * 1e9),              # 0.5 CPU core restricts cryptomining/CPU hogs
    pids_limit=64,                          # Max 64 processes restricts fork bombs
    security_opt=["no-new-privileges:true"],
    command="sleep infinity",               # Stays alive for exec commands
)
```

**Critically:** every container is forcefully destroyed inside a `finally` block in `repair_service.py`. No container leaks or persists beyond an iteration crash.

### 10.4 Code Injection Mechanism
User code is streamed to `/submitted/code.php` inside the container via Python's `tarfile` module — utilizing an in-memory tar-streaming mechanism without touching the host filesystem.

The repair pipeline then:
1. Detects the PHP namespace.
2. Copies `code.php` to the correct location in the Laravel directory tree.
3. Automatically triggers `composer dump-autoload` to register the class.
4. Validates class-loading logic via `php artisan tinker`.

---

## 11. Services Deep-Dive

### `docker_service.py`

| Function | Purpose |
|----------|---------|
| `create_container()` | Spin up fresh container with security limits |
| `copy_code(container, code)` | Write PHP to `/submitted/code.php` via tar |
| `execute(container, command, timeout, user)` | Run shell command, return `ExecResult(stdout, stderr, exit_code, duration_ms)` |
| `destroy(container)` | Stop + remove container (always in `finally`) |
| `health_check()` | Ping Docker daemon |

`ExecResult.has_php_fatal` checks for PHP fatal errors that don't produce non-zero exit codes (PHP's inconsistent error handling).

All blocking Docker SDK calls run in `asyncio.run_in_executor()` to avoid blocking the async event loop.

---

### `boost_service.py`

**Laravel Boost** is a development package that exposes `artisan boost:schema` and `artisan boost:docs` commands to retrieve the current application's DB schema and relevant Laravel documentation.

The service runs these commands **inside the sandbox container** so it sees the exact Laravel project state, then returns the context as JSON for the AI prompt.

**Caching:** Results are stored in an in-process dict keyed by `SHA-256(laravel_version + error_text[:500])`. Identical errors within a session skip the Docker exec entirely.

---

### `ai_service.py`

The AI service:
1. Builds the prompt from `repair_prompt.txt` template using `.replace()` (not f-strings — safer with PHP code containing curly braces)
2. Routes to the configured provider via a dispatch dict
3. Parses the JSON response — including fixing common escape issues where PHP namespaces (`App\Models\Product`) break JSON without double-escaping
4. Retries up to 3× on `ValueError` / `JSONDecodeError` via `tenacity`

**The repair prompt template** explicitly instructs the LLM to:
- Return **only** valid JSON — no prose, no markdown
- Fix **only** what is broken (minimal patch)
- Use one of three patch actions: `replace`, `append`, `create_file`
- Produce a deterministic Pest test (no network calls, no time-dependent logic)

---

### `sandbox_service.py`

Extracted from `repair_service.py`. Each function does one thing inside the container:

| Function | Purpose |
|---|---|
| `detect_class_info()` | PHP one-liners parse namespace + classname; builds `ClassInfo` |
| `setup_sqlite()` | Switches sandbox to SQLite (required under `--network=none`) |
| `place_code_in_laravel()` | PSR-4 placement + Tinker validation + `CLASS_OK` sentinel |
| `scaffold_route()` | Idempotent `Route::apiResource()` append to `routes/api.php` |
| `generate_baseline_pest_test()` | System-controlled HTTP assertion (no AI involvement) |
| `run_pest_test()` | `pest --filter=RepairTest --no-coverage` |
| `capture_laravel_log()` | Last 40 lines of `storage/logs/laravel.log` on Pest failure |
| `lint_test_file()` | `php -l RepairTest.php` before mutation gate |
| `run_mutation_test()` | `pest --mutate`; classifies output into 4 categories |
| `parse_mutation_score()` | 6-pattern regex with ANSI stripping; returns 0.0 on no match |
| `ensure_covers_directive()` | Injects `covers()` + `use function Pest\Laravel\{...};` |

---

### `patch_service.py`

Two permitted patch actions:

```
full_replace → replaces entire file content with replacement
create_file  → signals loop to write new file; current_code unchanged
```

`replace` and `append` are **banned** — raise `PatchApplicationError` immediately.

Forbidden filenames (`routes/api.php`, `routes/web.php`, etc.) are blocked silently — logged and skipped, not raised.

`apply_all()` processes a list of `PatchSpec` objects and returns `ApplyAllResult(updated_code, created_files, actions_taken, skipped_forbidden)`.

---

### `escalation_service.py`

4-rule stuck-loop detector evaluated after every failed iteration:
1. **Repeated diagnoses** — fuzzy match ≥ 70% word overlap across last 2 attempts → forces different reasoning
2. **Consecutive patch failures** → forces `full_replace`
3. **`create_file` without fixing original** → demands `full_replace` of the original file
4. **Dependency Guard** — same `create_file` path used more than once → forbids re-creating it

---

### `context_service.py`

200-item `deque` sliding window. On success, `store_repair_summary()` persists a `RepairSummary` row and appends to the deque immediately. On each new repair, `retrieve_similar_repairs()` scores entries by `(similarity × 0.7 + efficiency × 0.3)` and injects top-3 as prompt addendum.

---

### `repair_service.py`

The orchestrator — 413 lines. Key design decisions:

**Single persistent container** — created once before the iteration loop, destroyed in `finally`. Files from `create_file` patches persist naturally across iterations.

**`_normalize_code()`** — strips CRLF and UTF-8 BOM from submitted code on first receipt.

**`_normalize_migration()`** — converts named-class migrations to anonymous class syntax to prevent `Cannot redeclare class` errors.

**`iter_mutation_score` tracking** — partial mutation score stored on every iteration (even fails) so the research dataset has full score distributions.

**Laravel log capture** — on Pest failure, last 40 lines of `laravel.log` appended to `error_text` to surface the real PHP exception.

**Mutation score acceptance override** — if previous action was `create_file` and mutation score is 0%, system accepts it as success (boilerplate files have no mutations to test).

---

## 12. Database Schema

SQLite database at `data/repair.db` (created automatically on first startup).

### `submissions` Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID string | Primary key |
| `user_id` | String (nullable) | Optional — for multi-user deployments |
| `created_at` | DateTime (UTC) | Submission timestamp |
| `original_code` | Text | Raw broken code as submitted |
| `user_prompt` | Text (nullable) | Optional extra instructions from user |
| `status` | String(20) | `pending` → `running` → `success` / `failed` |
| `total_iterations` | Integer | How many iterations ran |
| `final_code` | Text (nullable) | Repaired code if status=success |
| `error_summary` | Text (nullable) | Human-readable failure reason |
| `case_id` | String (nullable) | Batch evaluation case identifier |
| `category` | String (nullable) | Error category (e.g. `missing_model`) |
| `experiment_id` | String (nullable) | Batch run identifier |

### `iterations` Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID string | Primary key |
| `submission_id` | UUID FK | Foreign key → submissions |
| `iteration_num` | Integer | 0-indexed iteration number |
| `code_input` | Text | Code version at start of this iteration |
| `execution_output` | Text | Container stdout |
| `error_logs` | Text | Combined stderr + stdout + Laravel log tail |
| `boost_context` | Text | JSON from boost_service |
| `ai_prompt` | Text | Full prompt sent to LLM |
| `ai_response` | Text | Raw LLM response JSON |
| `ai_model_used` | String(100) | e.g. `"nvidia/Qwen/Qwen2.5-Coder-32B-Instruct"` |
| `patch_applied` | Text | Stringified list of `PatchSpec` objects |
| `pest_test_code` | Text | AI-generated Pest test code |
| `pest_test_result` | Text | Pest output |
| `mutation_score` | Float | Score% from pest --mutate (NULL if gate not reached) |
| `status` | String(20) | `failed` or `success` |
| `duration_ms` | Integer | Iteration wall time in ms |
| `created_at` | DateTime (UTC) | Iteration start time |

### `repair_summaries` Table

Populated only on successful repairs. Feeds the sliding window memory.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID string | Primary key |
| `error_type` | String(255) | Extracted error signature (canonical key) |
| `diagnosis` | Text | What the AI diagnosed |
| `fix_applied` | Text | What fix was applied |
| `what_did_not_work` | Text (nullable) | Dead-end approaches from previous iterations |
| `iterations_needed` | Integer | How many iterations the repair took |
| `created_at` | DateTime (UTC) | When this repair was recorded |

---

## 13. Testing Guide

Tests live in `tests/`. All unit tests use mocks — **no real Docker or AI calls needed**.

### Run Unit Tests

```bash
source venv/bin/activate

# All unit tests (fast, no Docker needed)
pytest tests/ -m "not integration" -v

# Specific service
pytest tests/test_repair_service.py -v
pytest tests/test_ai_service.py -v
pytest tests/test_patch_service.py -v
pytest tests/test_boost_service.py -v
```

### Run Integration Tests

Integration tests require Docker and a real AI API key:

```bash
# Ensure Docker is running and .env has a valid AI key
pytest tests/integration/ -v --timeout=120
```

### Unit Test Coverage

| Test File | What It Tests |
|-----------|--------------|
| `test_repair_service.py` | Repair loop: success path, exhausted iterations, weak mutation score |
| `test_ai_service.py` | JSON parsing, prompt building, JSON escape repair |
| `test_boost_service.py` | Context fetching, caching, component type detection |
| `test_patch_service.py` | All three patch actions, error on missing target |

### Key Test Patterns

Tests mock the entire Docker layer using `unittest.mock.AsyncMock`:

```python
with (
    patch("api.services.repair_service.docker_service.create_container", AsyncMock(return_value=MagicMock())),
    patch("api.services.repair_service.docker_service.execute",
          AsyncMock(side_effect=[lint_ok, ns_ok, cls_ok, tinker_ok, pest_ok, mut_ok])),
    ...
):
    events = await _collect(run_repair_loop(...))
```

Events are collected from the async generator and asserted against — `status=success`, `mutation_score >= 80`, etc.

### `pytest.ini` Configuration

```ini
[pytest]
asyncio_mode = auto
markers =
    integration: marks tests as integration tests (require Docker+API key, slow)
```

`asyncio_mode=auto` means all `async def test_...` functions run automatically without needing `@pytest.mark.asyncio`.

---

## 14. MCP Integration (Cursor / Claude Code)

The platform exposes itself as an **MCP (Model Context Protocol)** tool server, allowing AI coding assistants like Cursor or Claude Code to call it directly.

### Cursor Setup

Create `.cursor/mcp.json` in your project:

```json
{
  "laravel-repair": {
    "command": "python",
    "args": ["mcp/server.py"],
    "env": {
      "REPAIR_API_URL": "http://localhost:8000"
    }
  }
}
```

### Available MCP Tool

**`repairLaravelApiCode`**

Parameters:
- `code` (string, required): Broken PHP/Laravel REST API code
- `max_iterations` (integer, optional, 1–10): Default 7

Returns:
```json
{
  "status": "success",
  "submission_id": "...",
  "iterations": 2,
  "repaired_code": "<?php\n...",
  "diagnosis": "App\\Models\\Product class did not exist",
  "mutation_score": 87.5
}
```

### Protocol

The MCP server uses **JSON-RPC 2.0 over stdio** transport — standard for MCP. It:
1. Receives `tools/list` requests and describes the available tool
2. Receives `tools/call` requests, submits code to the FastAPI backend, and polls until done
3. Streams the final result back as a JSON text block

The server polls every 1.5 seconds with a 10-minute timeout.

---

## 15. Security Model

### Threat: Code Injection

**Risk:** Submitted PHP code could be malicious (delete files, spawn processes, make network calls).

**Mitigation:** Code runs **exclusively inside Docker**. The Python application never executes PHP code directly. Every container has:
- `--network=none` — zero internet access
- `--memory=512m` — prevents OOM attacks
- `--pids-limit=64` — prevents fork bombs
- `--security-opt=no-new-privileges:true` — prevents privilege escalation

### Threat: Container Leaks

**Risk:** A crashed iteration could leave containers running, consuming resources.

**Mitigation:** Every `create_container()` call is paired with `destroy()` inside a `finally` block:

```python
container = None
try:
    container = await docker_service.create_container()
    ...
except Exception:
    ...
finally:
    if container:
        await docker_service.destroy(container)  # Always runs
```

### Threat: API Key Exposure

**Risk:** Committing `.env` to git exposes API keys.

**Mitigation:** `.env` is in `.gitignore`. Only `.env.example` (with placeholder values) is committed. Settings are loaded exclusively through `api/config.py` — never read directly from `os.environ` elsewhere.

### Threat: Oversized Code Submission

**Risk:** Submitting a 100MB PHP file causes memory/timeout issues.

**Mitigation:** `POST /api/repair` validates code size against `MAX_CODE_SIZE_KB` (default 100KB) and returns HTTP 400 if exceeded.

---

## 16. Thesis Batch Evaluation

`batch_manifest.yaml` defines all parameters for the thesis experiments.

```yaml
project_name: laravel-ai-repair
ai_provider: anthropic
ai_model: claude-sonnet-4-6
ai_temperature: 0.0          # Deterministic — critical for thesis reproducibility
max_iterations: 7
mutation_score_threshold: 80
batch_size: 10

resource_limits:
  cpus: "0.5"
  memory: 512m
  pids: 64
  timeout_s: 90

# Ablation flags — run without one to measure its contribution
use_boost_context: true      # Set false to test without Laravel Boost
use_mutation_gate: true      # Set false to test without mutation validation

cases:
  - id: case-001
    type: missing_model        # Class referenced but never created
  - id: case-002
    type: wrong_namespace      # Namespace doesn't match file path
  - id: case-003
    type: missing_import       # Facade used without importing
```

### Running a Batch

```bash
# Run single evaluation case
bash scripts/run_case.sh case-001

# Run full batch via API
curl -X POST http://localhost:8000/api/evaluate
```

Results are written to `tests/integration/results/batch_report.csv`.

### Ablation Study Design

The manifest supports two ablation flags:
- `use_boost_context: false` — disables Laravel Boost context enrichment (measures Boost's contribution)
- `use_mutation_gate: false` — disables the 80% mutation threshold (measures mutation gate's contribution)

---

## 17. Troubleshooting

### `laravel-sandbox:latest` image not found

```
docker build -t laravel-sandbox:latest ./docker/laravel-sandbox/
```

Allow 5 minutes on first run.

### `Docker daemon unreachable`

- Open Docker Desktop on Windows
- Go to Settings → Resources → WSL Integration
- Enable integration for your Ubuntu distro
- Restart Docker Desktop

### `APIStatusError: 401` or `AuthenticationError`

Your API key is incorrect or not set in `.env`. Check:
```bash
grep API_KEY .env
```

### Mutation tests report 0% but code is correct

This happens when the submitted file has no logic to mutate (e.g. a pure boilerplate Model file). The system automatically accepts `0%` as success if the previous patch action was `create_file`.

### `PatchApplicationError: Patch target not found`

The LLM returned a `replace` patch with a `target` string that doesn't exist in the current code. This is typically caused by:
- The model returning slightly reformatted code as the target
- The code having been modified in a previous iteration

The loop continues and the AI receives the error on its next attempt.

### Database issues

Delete `data/repair.db` to start fresh — the tables are recreated automatically on next startup.

### Logs show `[Global]` instead of the submission ID

This is a known open issue. Only `repair_service.py` uses a `LoggerAdapter` with `submission_id`. All other services (`boost_service`, `docker_service`, `sandbox_service`, `patch_service`) use plain `logger.info()` which defaults to `"Global"` in the log format. You cannot currently filter the log file by a specific submission ID. Workaround: filter by the submission UUID string using `grep`:

```bash
grep "<your-submission-uuid>" data/logs/repair_platform.log
```

### Mutation score shows 0% with no explanation

The mutation score parser (`parse_mutation_score`) returns `0.0` silently when none of its 6 regex patterns match the Pest output. This is a known gap — no SSE event is emitted. Check the raw `ai_response` in the DB or the log file for the full Pest output to diagnose.

---

*Built for BSc Thesis — Adamu Joseph Obinna, 2026*

```


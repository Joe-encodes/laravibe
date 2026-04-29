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

def _get_plan_prompt() -> str: return _load("role_plan_prompt.md")
def _get_verify_prompt() -> str: return _load("role_verify_prompt.md")
def _get_execute_prompt() -> str: return _load("role_execute_prompt.md")
def _get_review_prompt() -> str: return _load("role_review_prompt.md")
def _get_post_mortem_prompt() -> str: return _load("role_post_mortem_prompt.md")


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

# ── Model pools ──────────────────────────────────────────────────────────────
# Priority order: best quality/speed first, fallbacks at end.
# Cerebras and Dashscope are always last-resort backups.
# NOTE: Nvidia has higher TPM limits and is reserved as Executor primary.

PLANNER_POOL: list[tuple[str, str]] = _build_pool_from_config([
    ("groq",       "llama-3.3-70b-versatile"),    # Strong logic, fast
    ("cerebras",   "llama-3.3-70b"),              # Blazing fast fallback
    ("dashscope",  "qwen3-max"),                   # High-quota fallback
    ("nvidia",     "meta/llama-3.3-70b-instruct"),# Last resort
])

VERIFIER_POOL: list[tuple[str, str]] = _build_pool_from_config([
    ("groq",       "llama-3.3-70b-versatile"),
    ("cerebras",   "llama-3.3-70b"),
    ("dashscope",  "qwen3-max"),
    ("nvidia",     "meta/llama-3.3-70b-instruct"),
])

EXECUTOR_POOL: list[tuple[str, str]] = _build_pool_from_config([
    ("nvidia",     "meta/llama-3.3-70b-instruct"),# Primary: highest quality XML
    ("groq",       "llama-3.3-70b-versatile"),
    ("cerebras",   "llama-3.3-70b"),
    ("dashscope",  "qwen3-max"),
])

REVIEWER_POOL: list[tuple[str, str]] = _build_pool_from_config([
    ("groq",       "llama-3.3-70b-versatile"),
    ("cerebras",   "llama-3.3-70b"),
    ("dashscope",  "qwen3-max"),
    ("nvidia",     "meta/llama-3.3-70b-instruct"),
])

POST_MORTEM_POOL: list[tuple[str, str]] = _build_pool_from_config([
    ("groq",       "llama-3.3-70b-versatile"),
    ("cerebras",   "llama-3.3-70b"),              # Was missing — caused fatal crashes
    ("dashscope",  "qwen3-max"),
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

def _parse_retry_after(exc: Exception) -> float | None:
    """
    Extract the 'try again in Xs' hint from a Groq/Cerebras 429 error message.
    Returns seconds to sleep, or None if not parseable.
    """
    import re as _re
    msg = str(exc)
    m = _re.search(r'try again in ([\d.]+)s', msg, _re.IGNORECASE)
    if m:
        return min(float(m.group(1)) + 0.5, 15.0)  # cap at 15s
    if "rate_limit_exceeded" in msg or "429" in msg:
        return 5.0  # safe default
    return None


async def _call_role_pool(
    prompt: str,
    pool: list[tuple[str, str]],
    role_name: str,
    json_mode: bool = False,
) -> tuple[str, str]:
    """
    Try providers in pool order with smart 429 backoff.
    Returns (response_text, model_identifier).
    Raises AIServiceError if every provider fails.
    """
    import asyncio as _asyncio
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
            # If rate-limited, sleep the recommended duration before trying the next provider.
            # This respects API windows and prevents hammering subsequent providers.
            sleep_s = _parse_retry_after(exc)
            if sleep_s:
                logger.info(f"[AI/{role_name}] Rate-limited by {provider}. Sleeping {sleep_s:.1f}s before next provider.")
                await _asyncio.sleep(sleep_s)

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
        _get_plan_prompt(),
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
        _get_verify_prompt(),
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
        _get_execute_prompt(),
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
        _get_review_prompt(),
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
        _get_post_mortem_prompt(),
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

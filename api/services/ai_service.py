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
import html
from dataclasses import dataclass

import httpx

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
    reviewer_evidence: dict | None = None


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
    "cerebras":  {"base_url": "https://api.cerebras.ai/v1",                             "key_attr": "cerebras_api_key",   "default_model": "llama3.1-8b"},
    "groq":      {"base_url": "https://api.groq.com/openai/v1",                         "key_attr": "groq_api_key",       "default_model": "llama-3.3-70b-versatile"},
    "gemini":    {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/","key_attr": "gemini_api_key",     "default_model": "gemini-2.5-flash"},
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

# Planner needs strong logic + reliable JSON.
# We prioritize Groq and Cerebras for speed, followed by Gemini.
PLANNER_POOL: list[tuple[str, str]] = _build_pool_from_config([
    ("groq",       "llama-3.3-70b-versatile"),    # Fast but rate-limited
    ("cerebras",   "llama3.1-8b"),              # Blazing fast fallback
    ("gemini",     "gemini-2.5-flash"),           # Strong reasoning fallback
    ("dashscope",  "qwen3-max"),                   # High quota, strong reasoning
    ("nvidia",     "meta/llama-3.3-70b-instruct"),# Last resort
])

# Verifier needs same JSON reliability as Planner
VERIFIER_POOL: list[tuple[str, str]] = _build_pool_from_config([
    ("groq",       "llama-3.3-70b-versatile"),
    ("cerebras",   "llama3.1-8b"),
    ("gemini",     "gemini-2.5-flash"),
    ("dashscope",  "qwen3-max"),
    ("nvidia",     "meta/llama-3.3-70b-instruct"),
])

# Executor needs best XML/PHP code quality — Nvidia first (40 RPM, best 70B quality)
EXECUTOR_POOL: list[tuple[str, str]] = _build_pool_from_config([
    ("nvidia",     "meta/llama-3.3-70b-instruct"),# Primary: highest quality XML
    ("dashscope",  "qwen3-max"),                   # Strong coding fallback
    ("groq",       "llama-3.3-70b-versatile"),
    ("cerebras",   "llama3.1-8b"),
    ("gemini",     "gemini-2.5-flash"),
])

# Reviewer needs XML parsing quality
REVIEWER_POOL: list[tuple[str, str]] = _build_pool_from_config([
    ("groq",       "llama-3.3-70b-versatile"),
    ("cerebras",   "llama3.1-8b"),
    ("gemini",     "gemini-2.5-flash"),
    ("dashscope",  "qwen3-max"),
    ("nvidia",     "meta/llama-3.3-70b-instruct"),
])

POST_MORTEM_POOL: list[tuple[str, str]] = _build_pool_from_config([
    ("groq",       "llama-3.3-70b-versatile"),
    ("cerebras",   "llama3.1-8b"),
    ("gemini",     "gemini-2.5-flash"),
    ("dashscope",  "qwen3-max"),
    ("nvidia",     "meta/llama-3.3-70b-instruct"),
])


# ── Provider calls ────────────────────────────────────────────────────────────

# Providers that support within-provider key rotation.
# When one key hits a 429, we immediately try the next key for the *same*
# provider before falling through to the next provider in the pool.
_MULTI_KEY_PROVIDERS = {"groq", "cerebras"}


def _get_provider_keys(provider: str) -> list[str]:
    """
    Return all configured API keys for a provider, in order.
    For groq/cerebras this may return up to 4 keys.
    For all other providers returns a single-item list (or empty).
    """
    if provider == "groq":
        return settings.groq_keys()
    if provider == "cerebras":
        return settings.cerebras_keys()
    cfg = _PROVIDERS.get(provider, {})
    key_attr = cfg.get("key_attr")
    if not key_attr:
        return []
    key = getattr(settings, key_attr, "")
    return [key] if key else []


async def _call_with_key(
    prompt: str,
    provider: str,
    model: str,
    api_key: str,
    json_mode: bool = False,
) -> str:
    """
    Low-level: call a single OpenAI-compatible provider with an explicit key.
    Raises on any error — caller handles retry/rotation.
    """
    cfg = _PROVIDERS.get(provider)
    if not cfg:
        raise AIServiceError(f"Unknown provider: {provider}")

    if provider == "ollama":
        api_key, base_url = "ollama", f"{settings.ollama_base_url}/v1"
    else:
        base_url = cfg["base_url"]

    if not base_url:
        raise AIServiceError(f"Provider {provider} has no base_url configured")

    if AsyncOpenAI is None:
        raise AIServiceError("AsyncOpenAI client class is None.")

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        max_retries=0,
        timeout=httpx.Timeout(connect=15.0, read=150.0, write=10.0, pool=5.0),
    )

    kwargs: dict = {
        "model":       model or cfg["default_model"],
        "temperature": 0.0 if json_mode else settings.ai_temperature,
        "max_tokens":  4096,
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


async def _call_openai_compatible(
    prompt: str,
    provider: str,
    model: str | None = None,
    json_mode: bool = False,
) -> str:
    """
    Dispatch to a provider. For groq/cerebras, this is a thin wrapper;
    key rotation is handled upstream in _call_provider_with_key_rotation.
    For all other providers, it resolves the single key and calls.
    """
    cfg = _PROVIDERS.get(provider)
    if not cfg:
        raise AIServiceError(f"Unknown provider: {provider}")

    if provider == "ollama":
        return await _call_with_key(
            prompt, provider, model or cfg["default_model"], "ollama", json_mode
        )

    keys = _get_provider_keys(provider)
    if not keys:
        raise AIServiceError(f"Provider '{provider}' has no API key configured")

    # For single-key providers, just call directly
    return await _call_with_key(
        prompt, provider, model or cfg["default_model"], keys[0], json_mode
    )


async def _call_provider_with_key_rotation(
    prompt: str,
    provider: str,
    model: str,
    role_name: str,
    json_mode: bool = False,
) -> str:
    """
    For groq and cerebras: cycle through ALL configured keys on 429 before
    giving up on this provider entirely.
    For other providers: single attempt (they have one key).

    Returns the response text on success.
    Raises the last exception if all keys are exhausted.
    """
    import asyncio as _asyncio
    cfg = _PROVIDERS.get(provider, {})
    resolved_model = model or cfg.get("default_model", "")
    keys = _get_provider_keys(provider)

    if not keys:
        raise AIServiceError(f"[{role_name}] {provider} has no API key configured — skipping")

    last_exc: Exception | None = None

    for key_index, api_key in enumerate(keys):
        key_label = f"key#{key_index + 1}"
        try:
            logger.info(f"[AI/{role_name}] {provider}/{resolved_model} [{key_label}]")
            text = await _call_with_key(
                prompt, provider, resolved_model, api_key, json_mode
            )
            if key_index > 0:
                logger.info(
                    f"[AI/{role_name}] {provider} succeeded on {key_label} after "
                    f"{key_index} key rotation(s)."
                )
            return text

        except Exception as exc:
            last_exc = exc
            msg = str(exc).lower()
            is_rate_limited = (
                "rate_limit" in msg
                or "429" in msg
                or "too many requests" in msg
                or "quota" in msg
            )

            if is_rate_limited and provider in _MULTI_KEY_PROVIDERS:
                # Only rotate keys on rate-limit errors
                next_key_num = key_index + 2  # human-readable
                if key_index + 1 < len(keys):
                    logger.warning(
                        f"[AI/{role_name}] {provider} {key_label} rate-limited — "
                        f"switching to key#{next_key_num} immediately."
                    )
                    # Brief pause to avoid hammering — much shorter than a full
                    # provider-level backoff since we own multiple keys
                    await _asyncio.sleep(0.3)
                    continue
                else:
                    logger.warning(
                        f"[AI/{role_name}] {provider} all {len(keys)} keys rate-limited — "
                        f"falling through to next provider."
                    )
                    raise
            else:
                # Non-rate-limit error (auth failure, bad response, etc.) — don't
                # burn through remaining keys, just raise immediately.
                logger.warning(
                    f"[AI/{role_name}] {provider}/{resolved_model} [{key_label}] "
                    f"non-retryable error: {exc}"
                )
                raise

    # Exhausted all keys
    raise last_exc or AIServiceError(f"{provider} all keys exhausted")


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
    Returns seconds to sleep before trying the NEXT PROVIDER (not next key —
    key rotation is handled inside _call_provider_with_key_rotation).
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
    Try providers in pool order. For groq/cerebras, key rotation is attempted
    transparently before moving to the next provider.
    Returns (response_text, model_identifier).
    Raises AIServiceError if every provider (including all their keys) fails.
    """
    import asyncio as _asyncio
    last_error: Exception | None = None

    for provider, model in pool:
        try:
            text = await _call_provider_with_key_rotation(
                prompt, provider, model, role_name, json_mode
            )
            if json_mode and "{" not in text:
                raise ValueError(f"{provider}/{model}: no JSON object in response")
            return text, f"{provider}/{model}"

        except Exception as exc:
            logger.warning(f"[AI/{role_name}] {provider}/{model} exhausted: {exc}")
            last_error = exc
            # Cross-provider backoff only when all keys of this provider are spent
            sleep_s = _parse_retry_after(exc)
            if sleep_s:
                logger.info(
                    f"[AI/{role_name}] All {provider} keys spent. "
                    f"Sleeping {sleep_s:.1f}s before next provider."
                )
                await _asyncio.sleep(sleep_s)

    raise AIServiceError(f"[{role_name}] All providers failed. Last: {last_error}")



# ── XML parsing (replaces JSON escape hell) ───────────────────────────────────

def _strip_think_blocks(raw: str) -> str:
    """Remove DeepSeek R1 <think>...</think> chain-of-thought blocks."""
    return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()



def _smart_unescape_code(content: str) -> str:
    """
    Surgically unescape code blocks. If the block contains XML entities like &gt; 
    or &lt;, we assume the AI escaped the whole block and we unescape it.
    Otherwise, we leave it raw to prevent corrupting PHP strings.
    """
    if not content:
        return ""
    
    # If we see common escaped arrows or brackets, the AI is likely in 'Escape Mode'
    if "&gt;" in content or "&lt;" in content or "&quot;" in content:
        return html.unescape(content)
    
    return content


def _parse_xml_response(raw: str) -> AIRepairResponse:
    """
    Parse the Executor/Reviewer XML output into an AIRepairResponse.
    Surgically handles unescaping to prevent code corruption.
    """
    text = _strip_think_blocks(raw)

    def _tag(name: str, is_code: bool = False) -> str:
        m = re.search(rf"<{name}>(.*?)</{name}>", text, re.DOTALL | re.IGNORECASE)
        if not m:
            return ""
        content = m.group(1).strip()
        if is_code:
            return _smart_unescape_code(content)
        return html.unescape(content)

    diagnosis       = _tag("diagnosis")
    fix_description = _tag("fix")
    thought_process = _tag("thought_process")
    # USE is_code=True for code blocks to enable smart unescaping
    pest_raw        = _tag("pest_test", is_code=True)

    # Parse <file action="..." path="...">...</file>
    # Flexible regex: matches <file ...> content </file> and then extracts attributes
    file_blocks = re.findall(r'<file\s+(.*?)>(.*?)</file>', text, re.DOTALL | re.IGNORECASE)
    
    patches: list[PatchSpec] = []
    for attr_str, content in file_blocks:
        # Extract action and path from the attribute string (supports either order)
        action_match = re.search(r'action=(["\'])(.*?)\1', attr_str, re.IGNORECASE)
        path_match   = re.search(r'path=(["\'])(.*?)\1', attr_str, re.IGNORECASE)
        
        if not path_match:
            continue
            
        action = action_match.group(2).strip() if action_match else "full_replace"
        path   = path_match.group(2).strip()
        
        if action not in ALLOWED_PATCH_ACTIONS:
            action = "full_replace" if "Controller" in path else "create_file"
        
        patches.append(PatchSpec(
            action=action,
            target=path,
            replacement=_sanitize_php(_smart_unescape_code(content.strip()), path),
            filename=path,
        ))

    if not patches and not diagnosis:
        logger.error(f"AI Parse Failure: Raw output did not contain <repair> tags or valid XML.\nRaw: {raw[:500]}...")
        # We return an object with a specific 'PARSING_FAILED' marker so the pipeline can escalate
        return AIRepairResponse(
            thought_process="PARSING_FAILED",
            diagnosis="CRITICAL: AI failed to output valid XML. It output prose instead.",
            fix_description="No fix provided",
            patches=[],
            pest_test="",
            raw=raw,
            prompt=""
        )

    return AIRepairResponse(
        thought_process=thought_process or None,
        diagnosis=diagnosis,
        fix_description=fix_description,
        patches=patches,
        pest_test=_sanitize_php(pest_raw, "pest_test.php"),
        raw=raw,
        prompt="",
    )


def _sanitize_php(code: str, file_path: str = "") -> str:
    """
    Minimal post-processing on raw PHP.
    """
    if not code:
        return code

    # Edge case: model output literal \\n instead of real newlines
    if "<?php\\n" in code or ("\\n" in code and "\n" not in code.strip()):
        code = code.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")

    # Enforce anonymous migration syntax ONLY for migration files
    if "database/migrations" in file_path.lower() or "migration" in file_path.lower():
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

def _estimate_tokens(text: str) -> int:
    """Rough token estimation (chars / 4). Safe for most models."""
    if not text:
        return 0
    return len(text) // 4


def _truncate_ctx(text: str, max_chars: int) -> str:
    """Cap a context field at max_chars, keeping start and end."""
    if not text or len(text) <= max_chars:
        return text
    # Keep first 70% and last 30%
    first_part = int(max_chars * 0.7)
    last_part = max_chars - first_part - 50
    return text[:first_part] + "\n\n[... TRUNCATED ...]\n\n" + text[-last_part:]


def _fmt_previous_attempts(previous_attempts: list[dict]) -> str:
    if not previous_attempts:
        return "None — this is the first attempt."
    
    # Only show last 3 attempts to save tokens and avoid confusion
    recent = previous_attempts[-3:]
    lines = []
    for i, a in enumerate(recent):
        # Fix: orchestrator uses 'files', not 'created_files'
        files = a.get("files", [])
        parts = [
            f"Attempt (Last-{len(recent)-i}):",
            f"  - Action:    {a.get('action', 'execute_plan')}",
            f"  - Diagnosis: {a.get('diagnosis', '?')}",
            f"  - Outcome:   {a.get('outcome', 'unknown')}",
        ]
        if files:
            parts.append("  - Files in container: " + ", ".join(files))
        
        if a.get("failure_reason"):
            parts.append(f"  - WHY IT FAILED: {a['failure_reason']}")
        if a.get("pm_category"):
            parts.append(f"  - ROOT CAUSE: {a['pm_category']}")
        if a.get("pm_strategy"):
            parts.append(f"  - NEXT STRATEGY: {a['pm_strategy']}")
        
        lines.append("\n".join(parts))
    
    combined = "\n\n".join(lines)
    # Cap total history at 3000 chars
    return _truncate_ctx(combined, 3000)


def _build_role_prompt(template: str, **kwargs: str) -> str:
    """Inject variables into template. Validates placeholders exist."""
    result = template
    for key, value in kwargs.items():
        placeholder = f"{{{key}}}"
        if placeholder not in template:
            # Only warn, don't crash, but this helps catch missing fields in md files
            logger.warning(f"Prompt template missing placeholder: {placeholder}")
        result = result.replace(placeholder, value or "")
    
    # Final check for unreplaced placeholders
    # We find all {key} in the ORIGINAL template and check if they were in kwargs
    template_placeholders = set(re.findall(r"\{(\w+)\}", template))
    passed_keys = set(kwargs.keys())
    unreplaced = [p for p in template_placeholders if p not in passed_keys and p != "main"]
    
    if unreplaced:
        logger.warning(f"Prompt template '{template[:30]}...' is missing required data for placeholders: {unreplaced}")
    
    tokens = _estimate_tokens(result)
    if tokens > 20000:
        logger.warning(f"CRITICAL: Final prompt is very large (~{tokens} tokens). Model may truncate.")
        
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
        code=_truncate_ctx(code, 6000),
        error=_truncate_ctx(error, 2000),
        boost_context=_truncate_ctx(boost_context, 3000),
        previous_attempts=_fmt_previous_attempts(previous_attempts),
        similar_past_repairs=_truncate_ctx(similar_past_repairs, 2000),
        post_mortem=_truncate_ctx(post_mortem, 2000),
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
        code=_truncate_ctx(code, 6000),
        error=_truncate_ctx(error, 2000),
        boost_context=_truncate_ctx(boost_context, 3000),
        planner_output=_truncate_ctx(planner_output, 4000),
        previous_attempts=_fmt_previous_attempts(previous_attempts or []),
    )
    raw, model_used = await _call_role_pool(prompt, VERIFIER_POOL, "Verifier", json_mode=True)
    data = _parse_json_safe(raw)

    verdict          = data.get("verdict", "APPROVED")
    approved_plan    = data.get("approved_plan")
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
    post_mortem_strategy: str = "",
    user_prompt: str | None = None,
) -> ExecuteResult:
    """Generate all PHP code from the approved plan. Returns XML output."""
    plan_str = json.dumps(approved_plan, ensure_ascii=False, indent=2)
    prompt = _build_role_prompt(
        _get_execute_prompt(),
        code=_truncate_ctx(code, 6000),
        error=_truncate_ctx(error, 2000),
        boost_context=_truncate_ctx(boost_context, 3000),
        approved_plan=_truncate_ctx(plan_str, 4000),
        escalation_context=_truncate_ctx(escalation_context, 2000),
        post_mortem_strategy=post_mortem_strategy,
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
                # Guard: if Reviewer dropped all patches, restore originals.
                # REVIEWER_PATCH_RESTORATION: search this tag in logs to audit
                # cases where the Reviewer silently accepted bad code.
                if not validated_resp.patches:
                    logger.warning(
                        "[Reviewer] [REVIEWER_PATCH_RESTORATION] Reviewer returned zero patches "
                        "in validated_output — restoring Executor originals. "
                        "Audit this: Reviewer may have rejected code without emitting ESCALATE."
                    )
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
                return html.unescape(m.group(1).strip()) if m else ""
            evidence = {
                "what_failed":    _ev_tag("what_failed"),
                "what_was_tried": _ev_tag("what_was_tried"),
                "recommendation": _ev_tag("recommendation"),
            }

    if repairs:
        logger.info(f"[Reviewer] Inline repairs: {repairs}")
        
    final_resp = validated_resp or (exec_result.response if exec_result else None)
    if final_resp:
        final_resp.reviewer_evidence = evidence

    return ReviewResult(
        verdict=verdict,
        retry_count=parsed_retry,
        repairs_made=repairs,
        validated_output=final_resp,
        escalation_reason=escalation_reason,
        evidence_for_next_cycle=evidence,
        model_used=model_used,
    )


# ── Role 5: Post-Mortem ───────────────────────────────────────────────────────


def _fallback_post_mortem(failure_reason: str) -> dict:
    """Provides a default strategy when the AI Critic fails (saves credits/fallback)."""
    strategies = {
        "patch_failed": {
            "analysis": "The previous patch failed to find the target string in the source file.",
            "category": "patch_alignment",
            "strategy": "You MUST use action='full_replace' for the next attempt. Do not attempt partial patches. Output the ENTIRE file content."
        },
        "syntax_error": {
            "analysis": "The generated code has a PHP syntax error (e.g. missing semicolon or brace).",
            "category": "syntax",
            "strategy": "Double check all braces and semicolons. Ensure you are not nesting classes or missing '<?php' tags."
        },
        "pest_failed": {
            "analysis": "The code applied successfully but the functional tests are still failing.",
            "category": "logic",
            "strategy": "The logical approach is incorrect. Re-read the requirements. Check if you missed an edge case like 404 handling or validation errors."
        },
        "mutation_failed": {
            "analysis": "The code passed tests but failed the mutation gate (too brittle).",
            "category": "brittleness",
            "strategy": "Remove hardcoded values. Use parameterized logic. Ensure the code handles generic cases, not just the one in the test."
        }
    }
    return strategies.get(failure_reason, {
        "analysis": f"The repair attempt failed with reason: {failure_reason}",
        "category": "unknown",
        "strategy": "Review the error trace carefully and try a different logical approach. Ensure all dependencies are imported."
    })



async def get_post_mortem(
    code: str,
    failed_attempts: list[dict],
    pest_output: str,
    laravel_log: str,
    boost_context: str,
    failure_reason: str = "unknown",
) -> PostMortemResult:
    """Analyze a failed repair attempt and generate a fix strategy."""
    try:
        prompt = _build_role_prompt(
            _get_post_mortem_prompt(),
            code=_truncate_ctx(code, 6000),
            failure_reason=failure_reason,
            failed_patches=json.dumps(failed_attempts[-2:], indent=2),
            pest_output=_truncate_ctx(pest_output, 3000),
            laravel_log=_truncate_ctx(laravel_log, 2000),
            boost_context=_truncate_ctx(boost_context, 3000),
        )
        raw, model_used = await _call_role_pool(prompt, POST_MORTEM_POOL, "PostMortem", json_mode=True)
        data = _parse_json_safe(raw)
        
        return PostMortemResult(
            analysis=data.get("failure_analysis", ""),
            category=data.get("root_cause_category", failure_reason),
            strategy=data.get("fix_strategy", ""),
            files_implicated=data.get("files_implicated", []),
            model_used=model_used,
            raw=raw,
        )
    except Exception as e:
        logger.error(f"[PostMortem] API call failed, using local fallback strategy. Error: {e}")
        fallback = _fallback_post_mortem(failure_reason)
        return PostMortemResult(
            analysis=fallback["analysis"] + " (LOCAL FALLBACK)",
            category=fallback["category"],
            strategy=fallback["strategy"],
            files_implicated=[],
            model_used="local_fallback",
            raw=json.dumps(fallback)
        )


def validate_prompts():
    """Verify that all role prompt templates have the required placeholders."""
    roles = {
        "Plan": (_get_plan_prompt(), ["code", "error", "boost_context", "previous_attempts"]),
        "Verify": (_get_verify_prompt(), ["code", "error", "planner_output"]),
        "Execute": (_get_execute_prompt(), ["code", "error", "approved_plan", "post_mortem_strategy"]),
        "Review": (_get_review_prompt(), ["executor_output", "approved_plan"]),
        "Post-Mortem": (_get_post_mortem_prompt(), ["code", "failure_reason", "pest_output", "boost_context", "failed_patches", "laravel_log"])
    }
    
    for role, (template, required) in roles.items():
        missing = [p for p in required if f"{{{p}}}" not in template]
        if missing:
            logger.error(f"CRITICAL: Prompt template '{role}' is missing required placeholders: {missing}")
        else:
            logger.debug(f"Prompt template '{role}' validated successfully.")

# Run validation on import
try:
    validate_prompts()
except Exception as e:
    logger.error(f"Failed to validate prompts at startup: {e}")

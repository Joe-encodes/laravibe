"""
api/services/ai_service.py — LLM integration with multi-provider fallback.
Calls the repair prompt with temperature=0.0. Retries on malformed JSON or rate limits.
"""
import json
import logging
import re
from dataclasses import dataclass
from string import Template

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
import httpx
try:
    import openai
except ImportError:
    openai = None

from api.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Load prompt templates once at import time
import pathlib
_PROMPTS_DIR = pathlib.Path(__file__).parent.parent / "prompts"
_PLAN_PROMPT_TEMPLATE    = (_PROMPTS_DIR / "role_plan_prompt.md").read_text(encoding="utf-8")
_VERIFY_PROMPT_TEMPLATE  = (_PROMPTS_DIR / "role_verify_prompt.md").read_text(encoding="utf-8")
_EXECUTE_PROMPT_TEMPLATE = (_PROMPTS_DIR / "role_execute_prompt.md").read_text(encoding="utf-8")
_REVIEW_PROMPT_TEMPLATE  = (_PROMPTS_DIR / "role_review_prompt.md").read_text(encoding="utf-8")


# ── Data Classes ──────────────────────────────────────────────────────────────

@dataclass
class PatchSpec:
    action: str          # replace | append | create_file
    target: str | None
    replacement: str
    filename: str | None


@dataclass
class AIRepairResponse:
    thought_process: str | None
    diagnosis: str
    fix_description: str
    patches: list[PatchSpec]
    pest_test: str
    raw: str             # original JSON string for DB storage
    prompt: str          # full system prompt used for this request
    model_used: str = "unknown"  # actual provider/model that generated the response


class AIServiceError(Exception):
    pass


REQUIRED_RESPONSE_KEYS = {"diagnosis", "fix_description", "patches", "pest_test"}
ALLOWED_PATCH_ACTIONS = {"full_replace", "create_file"}


# ── Prompt Building ──────────────────────────────────────────────────────────




# ── Response Parsing ─────────────────────────────────────────────────────────

def _fix_json_escapes(text: str) -> str:
    """Fix common LLM JSON escaping bugs."""
    # 0. Normalize line endings
    text = text.replace(r'\r\n', r'\n').replace(r'\r', r'\n')

    # 1. Handle models that escape dollar signs or parentheses (common in math/markdown modes)
    text = re.sub(r'\\+\$', '$', text)
    text = re.sub(r'\\+\(', '(', text)
    text = re.sub(r'\\+\)', ')', text)

    # 2. Fix unescaped backslashes (common in PHP namespaces like \App\Models)
    text = re.sub(r'(?<!\\)\\(?!["\\/bfnrtu])', r'\\\\', text)
    return text


def _sanitize_php_code(code: str) -> str:
    """Final safety check on PHP code produced by AI before it hits the sandbox."""
    if not code:
        return code

    # 0. Fix over-escaped JSON where newlines were rendered as literal '\n'
    # If the file starts with '<?php\n' (literal \n), or has no actual newlines, unescape it.
    if code.startswith('<?php\\n') or code.startswith('<?php\\r\\n') or ('\\n' in code and '\n' not in code.strip()):
        code = code.replace('\\n', '\n').replace('\\t', '\t').replace('\\r', '\r')

    # 1. Models like to escape dollar signs as \$ even inside what they think are strings.
    code = re.sub(r'(?<!\\)\\\$', '$', code)

    # 2. Enforcement of Anonymous Migrations (Thesis Requirement)
    # AI often forgets Rule #2 in the prompt. We convert 'class Name extends Migration' to 'return new class extends Migration'.
    if "extends Migration" in code and "return new class extends Migration" not in code:
        # Match 'class <AnyName> extends Migration'
        code = re.sub(
            r'class\s+\w+\s+extends\s+Migration',
            'return new class extends Migration',
            code,
            flags=re.MULTILINE
        )
        # Remove trailing closing brace of the class if we converted it (simplified heuristic)
        # This is risky but often necessary if the AI produced a full file.
        # Actually, let's just log it for now or rely on the AI following instructions.
        # Given the sandbox constraints, anonymous classes are safer.

    return code


def _extract_json_object(raw: str) -> str:
    """
    Extract the outermost JSON object from raw LLM output.

    Handles:
    - <think>...</think> blocks (DeepSeek R1 chain-of-thought)
    - Prose text before/after the JSON object
    - Markdown fences around the JSON (```json ... ```)
    - Unbalanced or malformed outer wrapper prose

    Uses brace-depth tracking rather than regex so it works on
    deeply nested JSON with escaped quotes and PHP namespace strings.
    """
    # 1. Strip <think>...</think> first (DeepSeek R1)
    text = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()

    # 2. Find the first '{' that starts a real JSON object
    start = text.find('{')
    if start == -1:
        raise ValueError("No JSON object found in LLM response")

    # 3. Walk forward tracking brace depth, respecting string boundaries
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text[start:], start):
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    raise ValueError("Unbalanced braces in LLM JSON response")


def _parse_response(raw: str) -> AIRepairResponse:
    """Parse the XML response from the Executor LLM."""
    
    diagnosis_match = re.search(r'<diagnosis>(.*?)</diagnosis>', raw, re.DOTALL)
    fix_match = re.search(r'<fix>(.*?)</fix>', raw, re.DOTALL)
    thought_match = re.search(r'<thought_process>(.*?)</thought_process>', raw, re.DOTALL)
    pest_match = re.search(r'<pest_test>(.*?)</pest_test>', raw, re.DOTALL)
    
    files = re.findall(r'<file\s+action="([^"]+)"\s+path="([^"]+)">(.*?)</file>', raw, re.DOTALL)

    diagnosis = diagnosis_match.group(1).strip() if diagnosis_match else ""
    fix_description = fix_match.group(1).strip() if fix_match else ""
    thought_process = thought_match.group(1).strip() if thought_match else ""
    pest_test = pest_match.group(1).strip() if pest_match else ""

    patches: list[PatchSpec] = []
    for action, path, content in files:
        if action not in ALLOWED_PATCH_ACTIONS:
            action = "full_replace" if "Controller" in path else "create_file"
        
        patches.append(PatchSpec(
            action=action,
            target=path,
            replacement=_sanitize_php_code(content.strip()),
            filename=path
        ))

    return AIRepairResponse(
        thought_process=thought_process,
        diagnosis=diagnosis,
        fix_description=fix_description,
        patches=patches,
        pest_test=_sanitize_php_code(pest_test),
        raw=raw,
        prompt="",  # filled in by get_repair()
    )


def _validate_response_payload(data: dict, model_identifier: str | None = None) -> None:
    """Strict gate for model output shape and patch compatibility."""
    missing = REQUIRED_RESPONSE_KEYS - set(data.keys())
    if missing:
        raise ValueError(
            f"Missing required keys {sorted(missing)} from model output"
            + (f" ({model_identifier})" if model_identifier else "")
        )

    if not isinstance(data.get("diagnosis"), str):
        raise ValueError("Field 'diagnosis' must be a string")
    if not isinstance(data.get("fix_description"), str):
        raise ValueError("Field 'fix_description' must be a string")
    if not isinstance(data.get("pest_test"), str):
        raise ValueError("Field 'pest_test' must be a string")

    patches_data = data.get("patches")
    if isinstance(patches_data, dict):
        patches_data = [patches_data]
    if not isinstance(patches_data, list):
        raise ValueError("Field 'patches' must be a list or object")

    for idx, p in enumerate(patches_data):
        if not isinstance(p, dict):
            raise ValueError(f"Patch #{idx} is not an object")
        action = p.get("action")
        if action not in ALLOWED_PATCH_ACTIONS:
            raise ValueError(
                f"Patch #{idx} has unsupported action '{action}'. "
                f"Allowed: {sorted(ALLOWED_PATCH_ACTIONS)}"
            )
        if not isinstance(p.get("replacement"), str) or not p.get("replacement"):
            raise ValueError(f"Patch #{idx} has empty or invalid replacement")
        if action == "create_file":
            path = p.get("filename") or p.get("target") or p.get("path")
            if not isinstance(path, str) or not path.strip():
                raise ValueError(f"Patch #{idx} create_file missing filename/target/path")


def _parse_raw_json_payload(raw: str) -> dict:
    """Extract and parse raw model payload for pre-acceptance gating."""
    json_str = _extract_json_object(raw)
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        data = json.loads(_fix_json_escapes(json_str))
    if not isinstance(data, dict):
        raise ValueError("Model output root must be a JSON object")
    return data


# ── Provider Dispatch ────────────────────────────────────────────────────────

OPENAI_COMPATIBLE_PROVIDERS = {
    "qwen":     {"base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "key_attr": "dashscope_api_key",  "default_model": "qwen3-max"},
    "dashscope":{"base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "key_attr": "dashscope_api_key",  "default_model": "qwen3-max"},
    "nvidia":   {"base_url": "https://integrate.api.nvidia.com/v1",                    "key_attr": "nvidia_api_key",     "default_model": "meta/llama-3.3-70b-instruct"},
    "cerebras": {"base_url": "https://api.cerebras.ai/v1",                             "key_attr": "cerebras_api_key",   "default_model": "llama-3.3-70b"},
    "groq":     {"base_url": "https://api.groq.com/openai/v1",                         "key_attr": "groq_api_key",       "default_model": "llama-3.3-70b-versatile"},
    "gemini":   {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/","key_attr": "gemini_api_key",     "default_model": "gemini-2.0-flash"},
    "deepseek": {"base_url": "https://api.deepseek.com",                               "key_attr": "deepseek_api_key",   "default_model": "deepseek-coder"},
    "ollama":   {"base_url": None,                                                     "key_attr": None,                 "default_model": "qwen2.5-coder:7b"},
    "openai":   {"base_url": None,                                                     "key_attr": "openai_api_key",     "default_model": "gpt-4o"},
}
JSON_MODE_PROVIDERS = {"openai", "deepseek", "groq", "nvidia", "qwen", "dashscope"}

# Fallback order: Nvidia (primary logic), Dashscope (Ali/DeepSeek), then Groq/Cerebras/Gemini
FALLBACK_CHAIN = [
    ("nvidia",    "meta/llama-3.3-70b-instruct"),
    ("nvidia",    "meta/llama-4-maverick-17b-128e-instruct"),
    ("dashscope", "qwen-max"),
    ("dashscope", "qwen-plus"),
    ("dashscope", "deepseek-v3.2"),
    ("groq",      "llama-3.3-70b-versatile"),
    ("groq",      "qwen/qwen3-32b"),
    ("cerebras",  "qwen-3-235b-a22b-instruct-2507"),
    ("cerebras",  "llama3.1-8b"),
    ("gemini",    "gemini-2.5-flash"),
    ("gemini",    "gemini-2.5-flash-lite"),
]

# Rotation chain: Best models to cycle through iterations for cognitive diversity
# As requested: Qwen(Nvidia) -> DeepSeek(Alibaba/Dashscope) -> Llama(Nvidia) -> Gemini(Flash)
ROTATION_CHAIN = [
    ("nvidia",    "meta/llama-3.3-70b-instruct"),      # Iteration 0: stable
    ("dashscope", "qwen-max"),                         # Iteration 1: strong reasoning
    ("nvidia",    "meta/llama-3.3-70b-instruct"),      # Iteration 2: fallback to stable
    ("groq",      "llama-3.3-70b-versatile"),          # Iteration 3: fast fallback
    ("gemini",    "gemini-2.0-flash"),                 # Iteration 4: multimodal diversity
]

# ── Role-specific model pools ──────────────────────────────────────────────────────
# Planner/Verifier: fast, cheap, small JSON output (no code writing)
# Cerebras confirmed models: llama3.1-8b | qwen-3-235b-a22b-instruct-2507 | gpt-oss-120b
PLANNER_POOL = [
    ("gemini",    "gemini-2.5-flash-lite"),          # primary: fast + free
    ("groq",      "llama-3.3-70b-versatile"),         # fallback 1: strong reasoning
    ("groq",      "llama-3.1-8b-instant"),            # fallback 2: different TPM bucket
    ("cerebras",  "llama3.1-8b"),                     # fallback 3: guaranteed available
]
# Executor: strongest coder models
EXECUTOR_POOL = [
    ("nvidia",    "qwen/qwen2.5-coder-32b-instruct"),
    ("dashscope", "qwen-max"),
    ("cerebras",  "qwen-3-235b-a22b-instruct-2507"),
]
# Reviewer: best instruction followers for format validation
REVIEWER_POOL = [
    ("dashscope", "qwen-max"),
    ("cerebras",  "Qwen3-32B"),
    ("nvidia",    "qwen/qwen2.5-coder-32b-instruct"),
]


async def _call_openai_compatible(prompt: str, provider: str, model: str | None = None, json_mode: bool = True) -> str:
    """Single function for all OpenAI-compatible providers."""
    from openai import AsyncOpenAI

    config = OPENAI_COMPATIBLE_PROVIDERS[provider]

    # Ollama uses local URL, no real API key
    if provider == "ollama":
        api_key = "ollama"
        base_url = f"{settings.ollama_base_url}/v1"
    else:
        api_key = getattr(settings, config["key_attr"]) if config["key_attr"] else ""
        base_url = config["base_url"]

    client_kwargs = {
        "api_key": api_key,
        "max_retries": 0,
        "timeout": 60.0
    }
    if base_url:
        client_kwargs["base_url"] = base_url

    client = AsyncOpenAI(**client_kwargs)

    create_kwargs = {
        "model": model or config["default_model"],
        "temperature": settings.ai_temperature,
        "messages": [{"role": "user", "content": prompt}],
    }

    # Enforce JSON mode natively for robust parsing
    if json_mode and provider in JSON_MODE_PROVIDERS:
        create_kwargs["response_format"] = {"type": "json_object"}

    try:
        resp = await client.chat.completions.create(**create_kwargs)
    except Exception as exc:
        msg = str(exc).lower()
        # Some provider/model combinations reject response_format=json_object.
        if "response_format" in create_kwargs and (
            "extra_forbidden" in msg
            or "response_format" in msg
            or "unsupported" in msg
            or "422" in msg
        ):
            logger.warning(
                f"[AI] {provider}/{create_kwargs['model']} rejected JSON mode; retrying without response_format."
            )
            create_kwargs.pop("response_format", None)
            resp = await client.chat.completions.create(**create_kwargs)
        else:
            raise
    return resp.choices[0].message.content


async def _call_anthropic(prompt: str, model: str | None = None) -> str:
    """Anthropic uses its own SDK, not OpenAI-compatible."""
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model=model or settings.ai_model,
        max_tokens=4096,
        temperature=settings.ai_temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


async def _call_llm(prompt: str, iteration: int = 0) -> tuple[str, str]:
    """Route to the configured AI provider. Returns (text, model_identifier)."""
    provider = settings.default_ai_provider.lower()

    if provider == "fallback":
        return await _call_llm_with_fallback(prompt, iteration=iteration)
    if provider == "anthropic":
        text = await _call_anthropic(prompt)
        _validate_response_payload(_parse_raw_json_payload(text), model_identifier=f"anthropic/{settings.ai_model}")
        return text, f"anthropic/{settings.ai_model}"
    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        selected_model = settings.ai_model or OPENAI_COMPATIBLE_PROVIDERS[provider]["default_model"]
        text = await _call_openai_compatible(prompt, provider, model=selected_model)
        _validate_response_payload(_parse_raw_json_payload(text), model_identifier=f"{provider}/{selected_model}")
        model = selected_model
        return text, f"{provider}/{model}"

    raise AIServiceError(
        f"Unknown AI provider: '{provider}'. "
        f"Valid: fallback, anthropic, {', '.join(OPENAI_COMPATIBLE_PROVIDERS.keys())}"
    )


async def _call_llm_with_fallback(prompt: str, iteration: int = 0) -> tuple[str, str]:
    """Try providers in priority order, rotated by iteration.

    Returns (response_text, model_identifier) so callers can record which
    model actually produced the response — critical for research data integrity.
    """
    rot_idx = iteration % len(ROTATION_CHAIN)
    primary_model = ROTATION_CHAIN[rot_idx]

    effective_chain = [primary_model]
    for m in FALLBACK_CHAIN:
        if m != primary_model:
            effective_chain.append(m)

    last_error = None
    for provider, model in effective_chain:
        try:
            logger.info(f"[AI] Iteration {iteration}: Trying {provider}/{model}")
            text = await _call_openai_compatible(prompt, provider, model=model)
            try:
                _validate_response_payload(_parse_raw_json_payload(text), model_identifier=f"{provider}/{model}")
            except Exception as gate_exc:
                logger.warning(
                    f"[AI] Iteration {iteration}: {provider}/{model} failed output gate: {gate_exc}"
                )
                last_error = gate_exc
                continue
            return text, f"{provider}/{model}"
        except Exception as exc:
            logger.warning(f"[AI] Iteration {iteration}: {provider}/{model} failed: {exc}")
            last_error = exc

    raise AIServiceError(f"All fallback models failed for iteration {iteration}. Last: {last_error}")


# ── Retry Wrappers ────────────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((
        httpx.NetworkError, httpx.TimeoutException,
        getattr(openai, "RateLimitError", type(None)),
        getattr(openai, "APITimeoutError", type(None)),
        getattr(openai, "InternalServerError", type(None)),
    )),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
async def _call_llm_with_retry(prompt: str, iteration: int = 0) -> tuple[str, str]:
    """Add network/rate-limit retries to the LLM call. Returns (text, model_identifier)."""
    return await _call_llm(prompt, iteration=iteration)





# ── Role Pipeline Helpers ─────────────────────────────────────────────────────

async def _call_role_pool(prompt: str, pool: list[tuple[str, str]], role_name: str, json_mode: bool = True) -> tuple[str, str]:
    """
    Try providers in the given pool in order.
    Returns (response_text, model_identifier).
    Raises AIServiceError if all providers fail.
    """
    last_error = None
    for provider, model in pool:
        try:
            logger.info(f"[AI/{role_name}] Trying {provider}/{model}")
            text = await _call_openai_compatible(prompt, provider, model=model, json_mode=json_mode)
            # Basic check: must contain a JSON object if json_mode
            if json_mode and "{" not in text:
                raise ValueError(f"Response from {provider}/{model} contains no JSON object")
            return text, f"{provider}/{model}"
        except Exception as exc:
            logger.warning(f"[AI/{role_name}] {provider}/{model} failed: {exc}")
            last_error = exc

    raise AIServiceError(f"[{role_name}] All providers failed. Last error: {last_error}")


# ── Data classes for role pipeline ───────────────────────────────────────────

@dataclass
class PlanResult:
    """Output from the Planner role."""
    raw: str
    data: dict          # parsed JSON
    model_used: str


@dataclass
class VerifyResult:
    """Output from the Verifier role."""
    verdict: str        # "APPROVED" | "REJECT"
    approved_plan: dict | None
    corrections_made: list[str]
    reason: str         # populated on REJECT
    model_used: str
    raw: str


@dataclass
class ExecuteResult:
    """Output from the Executor role — same shape as AIRepairResponse."""
    response: AIRepairResponse
    model_used: str


@dataclass
class ReviewResult:
    """Output from the Reviewer role."""
    verdict: str                      # "APPROVED" | "ESCALATE"
    retry_count: int
    repairs_made: list[str]
    validated_output: AIRepairResponse | None   # populated on APPROVED
    escalation_reason: str            # populated on ESCALATE
    evidence_for_next_cycle: dict     # populated on ESCALATE
    model_used: str


# ── Role 1: Planner ───────────────────────────────────────────────────────────

async def get_plan(
    code: str,
    error: str,
    boost_context: str,
    previous_attempts: list[dict],
    similar_past_repairs: str = "",
) -> PlanResult:
    """
    Call the Planner role: classify the error and produce a structured repair plan.
    Returns PlanResult. Raises AIServiceError if all providers fail.
    """
    prev_str = _format_previous_attempts(previous_attempts)
    prompt = (
        _PLAN_PROMPT_TEMPLATE
        .replace("{code}", code)
        .replace("{error}", error)
        .replace("{boost_context}", boost_context or "")
        .replace("{previous_attempts}", prev_str)
        .replace("{similar_past_repairs}", similar_past_repairs)
    )

    raw, model_used = await _call_role_pool(prompt, PLANNER_POOL, "Planner")

    try:
        data = json.loads(_extract_json_object(raw))
    except Exception:
        data = json.loads(_fix_json_escapes(_extract_json_object(raw)))

    logger.info(f"[AI/Planner] Plan: {data.get('error_classification')} | confidence={data.get('plan_confidence')}")
    return PlanResult(raw=raw, data=data, model_used=model_used)


# ── Role 2: Verifier ──────────────────────────────────────────────────────────

async def verify_plan(
    code: str,
    error: str,
    boost_context: str,
    planner_output: str,
) -> VerifyResult:
    """
    Call the Verifier role: validate and optionally correct the Planner's plan.
    Returns VerifyResult. Verdict is "APPROVED" or "REJECT".
    """
    import json as _json

    prompt = (
        _VERIFY_PROMPT_TEMPLATE
        .replace("{code}", code)
        .replace("{error}", error)
        .replace("{boost_context}", boost_context or "")
        .replace("{planner_output}", planner_output)
    )

    raw, model_used = await _call_role_pool(prompt, PLANNER_POOL, "Verifier")  # same pool as Planner

    try:
        data = _json.loads(_extract_json_object(raw))
    except Exception:
        data = _json.loads(_fix_json_escapes(_extract_json_object(raw)))

    verdict = data.get("verdict", "APPROVED")
    approved_plan = data.get("approved_plan") if verdict == "APPROVED" else None
    corrections = data.get("corrections_made", [])
    reason = data.get("reason", "")

    if corrections:
        logger.info(f"[AI/Verifier] Corrections: {corrections}")

    return VerifyResult(
        verdict=verdict,
        approved_plan=approved_plan,
        corrections_made=corrections,
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
    """
    Call the Executor role: generate all PHP code from the approved plan.
    Returns ExecuteResult wrapping an AIRepairResponse.
    """
    import json as _json

    plan_str = _json.dumps(approved_plan, ensure_ascii=False, indent=2)
    prompt = (
        _EXECUTE_PROMPT_TEMPLATE
        .replace("{code}", code)
        .replace("{error}", error)
        .replace("{boost_context}", boost_context or "")
        .replace("{approved_plan}", plan_str)
        .replace("{escalation_context}", escalation_context)
        .replace("{user_prompt}", user_prompt or "")
    )

    raw, model_used = await _call_role_pool(prompt, EXECUTOR_POOL, "Executor", json_mode=False)

    # Parse using the existing response parser (same schema as get_repair)
    resp = _parse_response(raw)
    resp.prompt = prompt
    resp.model_used = model_used

    logger.info(f"[AI/Executor] {len(resp.patches)} patch(es) via {model_used}")
    return ExecuteResult(response=resp, model_used=model_used)


# ── Role 4: Reviewer ──────────────────────────────────────────────────────────

async def review_output(
    executor_output_raw: str,
    approved_plan: dict,
    retry_count: int = 0,
) -> ReviewResult:
    """
    Call the Reviewer role: validate Executor output format and structure.
    Returns ReviewResult with verdict APPROVED or ESCALATE.
    """
    import json as _json

    plan_str = _json.dumps(approved_plan, ensure_ascii=False, indent=2)
    prompt = (
        _REVIEW_PROMPT_TEMPLATE
        .replace("{executor_output}", executor_output_raw)
        .replace("{approved_plan}", plan_str)
        .replace("{retry_count}", str(retry_count))
    )

    raw, model_used = await _call_role_pool(prompt, REVIEWER_POOL, "Reviewer", json_mode=False)

    verdict_match = re.search(r'<review[^>]*verdict="([^"]+)"', raw, re.IGNORECASE)
    retry_match = re.search(r'<review[^>]*retry_count="(\d+)"', raw, re.IGNORECASE)
    
    verdict = verdict_match.group(1).upper() if verdict_match else "ESCALATE"
    parsed_retry_count = int(retry_match.group(1)) if retry_match else retry_count

    repairs = re.findall(r'<repair_action>(.*?)</repair_action>', raw, re.DOTALL | re.IGNORECASE)
    
    validated_resp = None
    if verdict == "APPROVED":
        validated_out_match = re.search(r'<validated_output>(.*?)</validated_output>', raw, re.DOTALL | re.IGNORECASE)
        if validated_out_match:
            try:
                validated_resp = _parse_response(validated_out_match.group(1))
                if not validated_resp.patches:
                    logger.warning("[AI/Reviewer] Reviewer returned an empty patches array. Restoring original patches.")
                    original_resp = _parse_response(executor_output_raw)
                    validated_resp.patches = original_resp.patches
                validated_resp.model_used = model_used
            except Exception as exc:
                logger.warning(f"[AI/Reviewer] Could not re-parse validated_output: {exc}. Escalating.")
                verdict = "ESCALATE"

    escalation_reason = ""
    evidence = {}
    if verdict == "ESCALATE":
        reason_match = re.search(r'<escalation_reason>(.*?)</escalation_reason>', raw, re.DOTALL | re.IGNORECASE)
        escalation_reason = reason_match.group(1).strip() if reason_match else ""
        
        evidence_match = re.search(r'<evidence_for_next_cycle>(.*?)</evidence_for_next_cycle>', raw, re.DOTALL | re.IGNORECASE)
        if evidence_match:
            ev_content = evidence_match.group(1)
            what_failed = re.search(r'<what_failed>(.*?)</what_failed>', ev_content, re.DOTALL | re.IGNORECASE)
            what_was_tried = re.search(r'<what_was_tried>(.*?)</what_was_tried>', ev_content, re.DOTALL | re.IGNORECASE)
            recommendation = re.search(r'<recommendation>(.*?)</recommendation>', ev_content, re.DOTALL | re.IGNORECASE)
            evidence = {
                "what_failed": what_failed.group(1).strip() if what_failed else "",
                "what_was_tried": what_was_tried.group(1).strip() if what_was_tried else "",
                "recommendation": recommendation.group(1).strip() if recommendation else ""
            }

    if repairs:
        logger.info(f"[AI/Reviewer] Inline repairs: {repairs}")

    return ReviewResult(
        verdict=verdict,
        retry_count=parsed_retry_count,
        repairs_made=repairs,
        validated_output=validated_resp,
        escalation_reason=escalation_reason,
        evidence_for_next_cycle=evidence,
        model_used=model_used,
    )


# ── Utility ───────────────────────────────────────────────────────────────────

def _format_previous_attempts(previous_attempts: list[dict]) -> str:
    """Format previous_attempts list into a readable string for role prompts."""
    if not previous_attempts:
        return "None — this is the first attempt."
    lines = []
    for i, a in enumerate(previous_attempts):
        created = a.get("created_files", [])
        parts = [
            f"Attempt {i + 1}:",
            f"  - Action: {a.get('action', '?')}",
            f"  - Diagnosis: {a.get('diagnosis', '?')}",
            f"  - Fix applied: {a.get('fix_description', '?')}",
            f"  - Outcome: {a.get('outcome', 'unknown')}",
        ]
        if created:
            parts.append("  - Files already in container: " + ", ".join(created))
        evidence = a.get("escalation_evidence")
        if evidence:
            parts.append(f"  - Reviewer evidence: {evidence}")
        lines.append("\n".join(parts))
    return "\n\n".join(lines)

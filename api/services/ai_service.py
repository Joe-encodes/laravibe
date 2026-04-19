"""
api/services/ai_service.py — LLM integration with multi-provider fallback.

Calls the repair prompt with temperature=0.0 for reproducibility.
Retries up to 3 times on malformed JSON (exponential backoff).
Retries up to 5 times on network/rate-limit errors.

All OpenAI-compatible providers (Qwen, NVIDIA, Cerebras, Groq, Gemini,
DeepSeek, Ollama) are handled by a single generic function + config dict.
Only Anthropic uses a separate function (different SDK).
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
_REPAIR_PROMPT_TEMPLATE = (_PROMPTS_DIR / "repair_prompt.md").read_text(encoding="utf-8")
_PEST_PROMPT_TEMPLATE = (_PROMPTS_DIR / "pest_prompt.md").read_text(encoding="utf-8")


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


class AIServiceError(Exception):
    pass


# ── Prompt Building ──────────────────────────────────────────────────────────

def _build_prompt(
    code: str, error: str, boost_context: str,
    iteration: int, previous_attempts: list[dict],
    escalation_context: str = "", similar_past_repairs: str = "",
    user_prompt: str | None = None,
) -> str:
    """Assemble the full repair prompt from template + runtime data."""
    if previous_attempts:
        prev = "\n".join(
            f"Attempt {i+1}: diagnosis={a.get('diagnosis','?')} | fix={a.get('fix_description','?')}"
            for i, a in enumerate(previous_attempts)
        )
    else:
        prev = "None — this is the first attempt."

    return (
        _REPAIR_PROMPT_TEMPLATE
        .replace("{code}", code)
        .replace("{error}", error)
        .replace("{boost_context}", boost_context or "No Boost context available.")
        .replace("{escalation_context}", escalation_context)
        .replace("{user_prompt}", user_prompt or "None provided.")
        .replace("{previous_attempts}", prev)
        .replace("{similar_past_repairs}", similar_past_repairs)
        .replace("{pest_template}", _PEST_PROMPT_TEMPLATE)
    )


# ── Response Parsing ─────────────────────────────────────────────────────────

def _fix_json_escapes(text: str) -> str:
    """Fix common LLM JSON escaping bugs."""
    # Dashscope and others often output unescaped backslashes in PHP namespaces
    # E.g. "covers(\App\..." instead of "covers(\\App\\..."
    # We replace any backslash that is ONLY a single backslash (not preceded by \)
    # and NOT followed by a valid JSON escape char
    text = re.sub(r'(?<!\\)\\(?!["\\/bfnrtu])', r'\\\\', text)
    return text


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
    """Parse the JSON response from the LLM. Raises ValueError on bad JSON."""
    try:
        json_str = _extract_json_object(raw)
    except ValueError:
        raise ValueError(f"Could not extract JSON object from response: {raw[:200]!r}")

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        data = json.loads(_fix_json_escapes(json_str))

    patches_data = data.get("patches")
    # Support legacy single "patch" key in case an old-format AI response arrives.
    if not patches_data:
        legacy_patch = data.get("patch")
        if isinstance(legacy_patch, dict):
            patches_data = [legacy_patch]
        else:
            patches_data = []

    # Safety: if the AI wrapped a single object in "patches" as a dict instead of list.
    if isinstance(patches_data, dict):
        patches_data = [patches_data]

    patches: list[PatchSpec] = []
    for p in patches_data:
        if not isinstance(p, dict):
            continue
        patches.append(PatchSpec(
            action=p.get("action", "full_replace"),
            target=p.get("target"),
            replacement=p.get("replacement", ""),
            filename=p.get("filename"),
        ))

    return AIRepairResponse(
        thought_process=data.get("thought_process"),
        diagnosis=data.get("diagnosis", ""),
        fix_description=data.get("fix_description", ""),
        patches=patches,
        pest_test=data.get("pest_test", ""),
        raw=raw,
        prompt="",  # filled in by get_repair()
    )


# ── Provider Dispatch ────────────────────────────────────────────────────────
# All OpenAI-compatible providers use a single generic function.
# Only Anthropic needs a separate implementation (different SDK).

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

# Fallback order: NVIDIA & Alibaba heavy, then Cerebras/Groq, then Gemini
FALLBACK_CHAIN = [
    ("nvidia",   "meta/llama-3.3-70b-instruct"),
    ("nvidia",   "nvidia/llama-3.3-nemotron-super-49b-v1.5"),
    ("nvidia",   "deepseek-ai/deepseek-r1-distill-llama-70b"),
    ("qwen",     "qwen3-max"),
    ("qwen",     "qwen3-coder"),
    ("qwen",     "qwen3-235b-a22b"),
    ("cerebras", "llama-3.1-70b"),
    ("cerebras", "qwen-3-235b-a22b-instruct-2507"),
    ("groq",     "llama-3.3-70b-versatile"),
    ("groq",     "llama-3.1-8b-instant"),
    ("gemini",   "gemini-3-flash-preview"),
]


async def _call_openai_compatible(prompt: str, provider: str, model: str | None = None) -> str:
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

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url

    client = AsyncOpenAI(**client_kwargs)

    create_kwargs = {
        "model": model or config["default_model"],
        "temperature": settings.ai_temperature,
        "messages": [{"role": "user", "content": prompt}],
    }

    # Enforce JSON mode natively for robust parsing
    if provider in ["openai", "deepseek", "groq", "nvidia", "qwen", "dashscope"]:
        create_kwargs["response_format"] = {"type": "json_object"}

    resp = await client.chat.completions.create(**create_kwargs)
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


async def _call_llm(prompt: str) -> str:
    """Route to the configured AI provider."""
    provider = settings.default_ai_provider.lower()

    if provider == "fallback":
        return await _call_llm_with_fallback(prompt)
    if provider == "anthropic":
        return await _call_anthropic(prompt)
    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        return await _call_openai_compatible(prompt, provider)

    raise AIServiceError(
        f"Unknown AI provider: '{provider}'. "
        f"Valid: fallback, anthropic, {', '.join(OPENAI_COMPATIBLE_PROVIDERS.keys())}"
    )


async def _call_llm_with_fallback(prompt: str) -> str:
    """Try providers in priority order until one succeeds."""
    last_error = None
    for provider, model in FALLBACK_CHAIN:
        try:
            logger.info(f"[AI] Trying {provider}/{model}")
            return await _call_openai_compatible(prompt, provider, model=model)
        except Exception as exc:
            logger.warning(f"[AI] {provider}/{model} failed: {exc}")
            last_error = exc
    raise AIServiceError(f"All fallback models failed. Last: {last_error}")


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
async def _call_llm_with_retry(prompt: str) -> str:
    """Add network/rate-limit retries to the LLM call."""
    return await _call_llm(prompt)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((ValueError, json.JSONDecodeError)),
    reraise=True,
)
async def get_repair(
    code: str, error: str, boost_context: str,
    iteration: int, previous_attempts: list[dict],
    escalation_context: str = "", similar_past_repairs: str = "",
    user_prompt: str | None = None,
) -> AIRepairResponse:
    """
    Call the LLM with the repair prompt.
    Retries up to 3× on malformed JSON, 5× on API errors.
    """
    prompt = _build_prompt(code, error, boost_context, iteration, previous_attempts, escalation_context, similar_past_repairs, user_prompt)

    if settings.debug:
        logger.debug(f"[AI] PROMPT:\n{prompt[:500]}...")

    try:
        raw = await _call_llm_with_retry(prompt)
        resp = _parse_response(raw)
        resp.prompt = prompt
        return resp
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning(f"[AI] Bad JSON on iteration {iteration}, retrying... ({exc})")
        raise
    except Exception as exc:
        raise AIServiceError(f"LLM call failed: {exc}") from exc

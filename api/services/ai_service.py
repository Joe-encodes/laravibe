"""
api/services/ai_service.py — LLM integration (Anthropic / OpenAI / Groq).

Calls the repair prompt with temperature=0.0 for reproducibility.
Retries up to 3 times on malformed JSON (exponential backoff).
"""
import json
import logging
import asyncio
import re
from dataclasses import dataclass
from string import Template

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from api.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Load prompt template once at import time
import pathlib
_PROMPT_PATH = pathlib.Path(__file__).parent.parent / "prompts" / "repair_prompt.txt"
_REPAIR_PROMPT_TEMPLATE = _PROMPT_PATH.read_text(encoding="utf-8")


@dataclass
class PatchSpec:
    action: str          # replace | append | create_file
    target: str | None
    replacement: str
    filename: str | None


@dataclass
class AIRepairResponse:
    diagnosis: str
    fix_description: str
    patch: PatchSpec
    pest_test: str
    raw: str             # original JSON string for DB storage


class AIServiceError(Exception):
    pass


def _build_prompt(
    code: str,
    error: str,
    boost_context: str,
    iteration: int,
    previous_attempts: list[dict],
) -> str:
    prev = ""
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
        .replace("{previous_attempts}", prev)
    )


def _fix_json_escapes(text: str) -> str:
    """
    Gemini (and other models) sometimes embed PHP namespace strings like
    App\Http\Controllers inside JSON without double-escaping the backslash.
    This pre-processes the raw JSON string to fix invalid \escape sequences
    before parsing, replacing lone backslashes with \\.
    Only fixes backslashes NOT followed by valid JSON escape characters.
    """
    return re.sub(r'\\(?!["\\/.bfnrtu])', r'\\\\', text)


def _parse_response(raw: str) -> AIRepairResponse:
    """Parse the JSON response from the LLM. Raises ValueError on bad JSON."""
    # Strip markdown fences if the model wrapped its JSON anyway
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    # Try raw parse first; if it fails due to bad escapes, repair and retry
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = json.loads(_fix_json_escapes(text))

    patch_data = data.get("patch", {})
    patch = PatchSpec(
        action=patch_data.get("action", "append"),
        target=patch_data.get("target"),
        replacement=patch_data.get("replacement", ""),
        filename=patch_data.get("filename"),
    )

    return AIRepairResponse(
        diagnosis=data.get("diagnosis", ""),
        fix_description=data.get("fix_description", ""),
        patch=patch,
        pest_test=data.get("pest_test", ""),
        raw=raw,
    )


async def _call_anthropic(prompt: str) -> str:
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model=settings.ai_model,
        max_tokens=4096,
        temperature=settings.ai_temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


async def _call_openai(prompt: str) -> str:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    resp = await client.chat.completions.create(
        model="gpt-4o",
        temperature=settings.ai_temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content


async def _call_groq(prompt: str) -> str:
    """Groq — free tier, llama-3.3-70b or deepseek-r1."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1",
    )
    resp = await client.chat.completions.create(
        model=settings.ai_model or "llama-3.3-70b-versatile",
        temperature=settings.ai_temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content


async def _call_gemini(prompt: str) -> str:
    """Google Gemini — genuinely free at aistudio.google.com.
    Uses the OpenAI-compatible endpoint (no extra SDK needed).
    Get key at: https://aistudio.google.com/app/apikey
    """
    from openai import AsyncOpenAI
    client = AsyncOpenAI(
        api_key=settings.gemini_api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    resp = await client.chat.completions.create(
        model=settings.ai_model or "gemini-2.5-flash",
        temperature=settings.ai_temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content


async def _call_deepseek(prompt: str) -> str:
    """DeepSeek — near-free, best code model available.
    Get key at: https://platform.deepseek.com
    """
    from openai import AsyncOpenAI
    client = AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url="https://api.deepseek.com",
    )
    resp = await client.chat.completions.create(
        model=settings.ai_model or "deepseek-coder",
        temperature=settings.ai_temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content


async def _call_ollama(prompt: str) -> str:
    """Ollama — fully local, no API key needed.
    Install: https://ollama.com  then run: ollama pull qwen2.5-coder:7b
    Needs 8GB RAM minimum. Good models: qwen2.5-coder:7b, codellama:7b
    """
    from openai import AsyncOpenAI
    client = AsyncOpenAI(
        api_key="ollama",          # Ollama ignores the key but the field is required
        base_url=f"{settings.ollama_base_url}/v1",
    )
    resp = await client.chat.completions.create(
        model=settings.ai_model or "qwen2.5-coder:7b",
        temperature=settings.ai_temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content


async def _call_llm(prompt: str) -> str:
    """Route to the configured AI provider."""
    provider = settings.default_ai_provider.lower()
    dispatch = {
        "gemini":    _call_gemini,      # Free — recommended
        "groq":      _call_groq,        # Free tier
        "deepseek":  _call_deepseek,    # Near-free, best code model
        "ollama":    _call_ollama,       # Local, no key needed
        "anthropic": _call_anthropic,   # Paid
        "openai":    _call_openai,      # Paid
    }
    if provider not in dispatch:
        raise AIServiceError(
            f"Unknown AI provider: '{provider}'. "
            f"Valid options: {', '.join(dispatch.keys())}"
        )
    return await dispatch[provider](prompt)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((ValueError, json.JSONDecodeError)),
    reraise=True,
)
async def get_repair(
    code: str,
    error: str,
    boost_context: str,
    iteration: int,
    previous_attempts: list[dict],
) -> AIRepairResponse:
    """
    Call the LLM with the repair prompt.
    Retries up to 3× on malformed JSON (exponential backoff).
    Raises AIServiceError after 3 failures.
    """
    prompt = _build_prompt(code, error, boost_context, iteration, previous_attempts)

    if settings.debug:
        logger.debug(f"[AI] PROMPT:\n{prompt[:500]}...")

    try:
        raw = await _call_llm(prompt)
        if settings.debug:
            logger.debug(f"[AI] RESPONSE:\n{raw[:500]}...")
        return _parse_response(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning(f"[AI] Bad JSON on iteration {iteration}, retrying... ({exc})")
        raise
    except Exception as exc:
        raise AIServiceError(f"LLM call failed: {exc}") from exc

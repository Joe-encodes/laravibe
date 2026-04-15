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

# Load prompt templates once at import time
import pathlib
_PROMPTS_DIR = pathlib.Path(__file__).parent.parent / "prompts"
_REPAIR_PROMPT_TEMPLATE = (_PROMPTS_DIR / "repair_prompt.txt").read_text(encoding="utf-8")
_PEST_PROMPT_TEMPLATE = (_PROMPTS_DIR / "pest_prompt.txt").read_text(encoding="utf-8")


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
    prompt: str          # full system prompt used for this request


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
        .replace("{pest_template}", _PEST_PROMPT_TEMPLATE)
    )



def _fix_json_escapes(text: str) -> str:
    r"""
    Gemini (and other models) sometimes embed PHP namespace strings like
    App\Http\Controllers inside JSON without double-escaping the backslash.
    This pre-processes the raw JSON string to fix invalid \escape sequences
    before parsing, replacing lone backslashes with \\.
    Only fixes backslashes NOT followed by valid JSON escape characters.
    """
    # Use a lambda to avoid any re.sub template string quirky parsing, 
    # and remove '.' since \. is not a valid JSON escape
    return re.sub(r'\\(?![\\"/bfnrtu])', lambda m: '\\\\', text)


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
        prompt="", # Initialized in get_repair
    )


async def _call_anthropic(prompt: str, model: str = None) -> str:
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model=model or settings.ai_model,
        max_tokens=4096,
        temperature=settings.ai_temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


async def _call_openai(prompt: str, model: str = None) -> str:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    resp = await client.chat.completions.create(
        model=model or settings.ai_model or "gpt-4o",
        temperature=settings.ai_temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content


async def _call_groq(prompt: str, model: str = None) -> str:
    """Groq — free tier, llama-3.3-70b or deepseek-r1."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1",
    )
    resp = await client.chat.completions.create(
        model=model or settings.ai_model or "llama-3.3-70b-versatile",
        temperature=settings.ai_temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content


async def _call_gemini(prompt: str, model: str = None) -> str:
    """Google Gemini — genuinely free at aistudio.google.com."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(
        api_key=settings.gemini_api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    resp = await client.chat.completions.create(
        model=model or settings.ai_model or "gemini-2.0-flash",
        temperature=settings.ai_temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content


async def _call_qwen(prompt: str, model: str = None) -> str:
    """Alibaba Qwen via DashScope — 1M free tokens, OpenAI-compatible."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(
        api_key=settings.dashscope_api_key,
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )
    resp = await client.chat.completions.create(
        model=model or settings.ai_model or "qwen3-max",
        temperature=settings.ai_temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content


async def _call_cerebras(prompt: str, model: str = None) -> str:
    """Cerebras — blazing fast inference (1000+ tok/s)."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(
        api_key=settings.cerebras_api_key,
        base_url="https://api.cerebras.ai/v1",
    )
    resp = await client.chat.completions.create(
        model=model or settings.ai_model or "llama-3.3-70b",
        temperature=settings.ai_temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content


async def _call_nvidia(prompt: str, model: str = None) -> str:
    """NVIDIA NIM — high performance, OpenAI-compatible."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(
        api_key=settings.nvidia_api_key,
        base_url="https://integrate.api.nvidia.com/v1",
    )
    resp = await client.chat.completions.create(
        model=model or settings.ai_model or "meta/llama-3.3-70b-instruct",
        temperature=settings.ai_temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content


async def _call_deepseek(prompt: str, model: str = None) -> str:
    """DeepSeek — near-free, best code model available."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url="https://api.deepseek.com",
    )
    resp = await client.chat.completions.create(
        model=model or settings.ai_model or "deepseek-coder",
        temperature=settings.ai_temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content


async def _call_ollama(prompt: str, model: str = None) -> str:
    """Ollama — fully local, no API key needed."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(
        api_key="ollama",
        base_url=f"{settings.ollama_base_url}/v1",
    )
    resp = await client.chat.completions.create(
        model=model or settings.ai_model or "qwen2.5-coder:7b",
        temperature=settings.ai_temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content


async def _call_llm_with_fallback(prompt: str) -> str:
    """Priority-based fallback mechanism for AI providers."""
    # List of models to try in order of priority (NVIDIA & Alibaba first as per user request)
    fallback_models = [
        # 1-3. NVIDIA NIM (Primary Weight)
        "nvidia_nim/meta/llama-3.3-70b-instruct",
        "nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "nvidia_nim/deepseek-ai/deepseek-r1-distill-llama-70b",
        
        # 4-6. Alibaba DashScope (Primary Weight)
        "dashscope/qwen3-max",
        "dashscope/qwen3-coder",
        "dashscope/qwen3-235b-a22b",
        
        # 7-8. Cerebras
        "cerebras/llama-3.1-70b",
        "cerebras/qwen-3-235b-a22b-instruct-2507",
        
        # 9-10. Groq
        "groq/llama-3.3-70b-versatile",
        "groq/llama-3.1-8b-instant",
        
        # 11. Gemini (Chill for now)
        "gemini/gemini-3-flash-preview",
    ]

    dispatch = {
        "nvidia_nim": _call_nvidia,
        "dashscope":  _call_qwen,
        "cerebras":   _call_cerebras,
        "groq":       _call_groq,
        "gemini":     _call_gemini,
        "deepseek":   _call_deepseek,
        "ollama":     _call_ollama,
        "anthropic":  _call_anthropic,
        "openai":     _call_openai,
    }

    last_error = None
    for full_model_path in fallback_models:
        try:
            # Parse provider and model
            if "/" not in full_model_path:
                logger.warning(f"[AI] Invalid fallback model format: {full_model_path}")
                continue
                
            provider_prefix, model_id = full_model_path.split("/", 1)
            
            if provider_prefix not in dispatch:
                logger.warning(f"[AI] Unknown provider in fallback: {provider_prefix}")
                continue

            logger.info(f"[AI] Attempting fallback model: {full_model_path}")
            return await dispatch[provider_prefix](prompt, model=model_id)
            
        except Exception as exc:
            logger.warning(f"[AI] Fallback failed for {full_model_path}: {exc}")
            last_error = exc
            continue

    raise AIServiceError(f"All AI fallback models failed. Last error: {last_error}")


async def _call_llm(prompt: str) -> str:
    """Route to the configured AI provider."""
    provider = settings.default_ai_provider.lower()
    
    if provider == "fallback":
        return await _call_llm_with_fallback(prompt)
        
    dispatch = {
        "qwen":      _call_qwen,        # Free 1M tokens — recommended
        "dashscope": _call_qwen,        # Alias
        "cerebras":  _call_cerebras,    # Blazing fast, generous limits
        "gemini":    _call_gemini,      # Free tier (rate-limited)
        "groq":      _call_groq,        # Free tier
        "deepseek":  _call_deepseek,    # Near-free, best code model
        "ollama":    _call_ollama,       # Local, no key needed
        "anthropic": _call_anthropic,   # Paid
        "openai":    _call_openai,      # Paid
        "nvidia":    _call_nvidia,      # High performance
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
        
        resp = _parse_response(raw)
        resp.prompt = prompt
        return resp
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning(f"[AI] Bad JSON on iteration {iteration}, retrying... ({exc})")
        raise
    except Exception as exc:
        raise AIServiceError(f"LLM call failed: {exc}") from exc

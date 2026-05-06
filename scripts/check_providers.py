#!/usr/bin/env python3
"""
scripts/check_providers.py — Ping every configured provider with a tiny prompt.
Prints a clear pass/fail table so you know exactly which keys work before a live test.

Usage:
    ./venv/bin/python3 scripts/check_providers.py
"""
import asyncio
import sys
import os

# Make sure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.services.ai_service import _call_openai_compatible, _PROVIDERS, AIServiceError
from api.config import get_settings

PING_PROMPT = "Reply with only the word PONG and nothing else."

PASS = "✅"
FAIL = "❌"
SKIP = "⏭️ "

# Providers to test (in the order they appear in pools)
TEST_PROVIDERS = [
    ("cerebras",  "llama3.1-8b"),
    ("groq",      "llama-3.3-70b-versatile"),
    ("dashscope", "qwen3-max"),
    ("nvidia",    "meta/llama-3.3-70b-instruct"),
    ("gemini",    "gemini-2.5-flash"),
]


async def ping(provider: str, model: str, settings) -> tuple[bool, str]:
    cfg = _PROVIDERS.get(provider, {})
    key_attr = cfg.get("key_attr")
    key = getattr(settings, key_attr, "") if key_attr else "NO_KEY_ATTR"
    
    if not key:
        return None, "no key configured"
    
    try:
        response = await asyncio.wait_for(
            _call_openai_compatible(PING_PROMPT, provider, model=model),
            timeout=20.0
        )
        ok = "pong" in response.lower() or len(response.strip()) < 80
        return ok, response.strip()[:60]
    except asyncio.TimeoutError:
        return False, "TIMEOUT (20s)"
    except AIServiceError as e:
        return False, str(e)[:80]
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:60]}"


async def main():
    settings = get_settings()
    
    print("\n🔍 LaraVibe Provider Sanity Check")
    print(f"   Default provider: {settings.default_ai_provider}")
    print(f"   Role pipeline:    {'ENABLED' if settings.use_role_pipeline else 'DISABLED'}")
    print("=" * 65)
    print(f"  {'Provider':<14} {'Model':<35} {'Status'}")
    print(f"  {'-'*60}")
    
    results = []
    for provider, model in TEST_PROVIDERS:
        print(f"  Testing {provider}/{model}...", end=" ", flush=True)
        ok, detail = await ping(provider, model, settings)
        
        if ok is None:
            icon = SKIP
            label = "SKIP — no key"
        elif ok:
            icon = PASS
            label = f"PASS → '{detail}'"
        else:
            icon = FAIL
            label = f"FAIL → {detail}"
        
        print(f"\r  {icon} {provider:<13} {model:<35} {label}")
        results.append((provider, ok))
    
    print("=" * 65)
    working = [p for p, ok in results if ok]
    failing = [p for p, ok in results if ok is False]
    skipped = [p for p, ok in results if ok is None]
    
    print(f"\n  ✅ Working : {', '.join(working) or 'none'}")
    print(f"  ❌ Failing : {', '.join(failing) or 'none'}")
    print(f"  ⏭️  No key  : {', '.join(skipped) or 'none'}")
    
    print("\n  Pool readiness:")
    print(f"  Planner/Verifier  → needs: dashscope, groq, cerebras, nvidia")
    print(f"  Executor (primary)→ needs: nvidia (then dashscope, groq, cerebras)")
    print(f"  Reviewer          → needs: dashscope, groq, cerebras, nvidia")
    
    if len(working) >= 2:
        print(f"\n  ✅ System has enough providers to run repairs.")
    else:
        print(f"\n  ⚠️  Only {len(working)} working provider(s) — rotation chain will be thin!")


if __name__ == "__main__":
    asyncio.run(main())

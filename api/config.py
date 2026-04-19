"""
api/config.py — Application settings loaded from .env via Pydantic Settings.
All config is centralised here. Never read env vars directly anywhere else.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


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
    max_code_size_kb: int = 100
    secret_key: str = "change-this-in-production"
    debug: bool = False

    # ── Mutation Gate ─────────────────────────────────────────────────────────
    mutation_score_threshold: int = 80       # pest --mutate must score >= this %




@lru_cache
def get_settings() -> Settings:
    """Cached singleton — call this everywhere instead of instantiating Settings()."""
    return Settings()

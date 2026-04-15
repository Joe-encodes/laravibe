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
    max_iterations: int = 7

    # ── App ───────────────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./data/repair.db"
    max_code_size_kb: int = 100
    secret_key: str = "change-this-in-production"
    debug: bool = False

    # ── Mutation Gate ─────────────────────────────────────────────────────────
    mutation_score_threshold: int = 80       # pest --mutate must score >= this %

    # ── Sandbox DB/Cache (passed into each Docker container) ─────────────────
    sandbox_db_host: str = "mysql"
    sandbox_db_port: int = 3306
    sandbox_db_database: str = "laravel"
    sandbox_db_username: str = "laravel"
    sandbox_db_password: str = "secret"
    sandbox_redis_host: str = "redis"


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — call this everywhere instead of instantiating Settings()."""
    return Settings()

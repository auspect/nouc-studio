"""Configuration and environment settings for Nouc Studio."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_global_memory_dir() -> Path:
    """Reuse existing pre-rename memory without moving or overwriting it."""
    legacy = Path.home() / ".prism-studio" / "memory"
    current = Path.home() / ".nouc-studio" / "memory"
    return legacy if legacy.exists() and not current.exists() else current


class InsightsConfig(BaseSettings):
    """Global and project-scoped configuration for Nouc Studio."""

    model_config = SettingsConfigDict(
        env_prefix="INSIGHTS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    project_root: Path = Field(
        default_factory=Path.cwd,
        description="Current workspace root directory.",
    )
    local_memory_dir: Path = Field(
        default_factory=lambda: Path.cwd() / ".insights" / "memory",
        description="Project-local self-healing failure/fix memory directory.",
    )
    global_memory_dir: Path = Field(
        default_factory=_default_global_memory_dir,
        description="Global cross-project self-healing memory directory.",
    )
    deepwiki_mcp_url: str = Field(
        default="https://mcp.deepwiki.com/mcp",
        description="DeepWiki MCP server endpoint for live repository documentation grounding.",
    )
    default_llm_model: str = Field(
        default="google:gemini-3.8-flash",
        description=(
            "Default PydanticAI model identifier verified via KnownModelName (e.g., "
            "'google:gemini-3.8-flash', 'google:gemini-4-argon', 'google-cloud:gemini-4-argon', "
            "'anthropic:claude-sonnet-5-5', 'anthropic:claude-opus-5-5', "
            "'openai:gpt-6-sol', 'openai:gpt-6.1-sol', 'ollama:qwen3-coder:30b', 'ollama:gemma4:31b', or 'offline')."
        ),
    )
    llm_base_url: str | None = Field(
        default=None,
        description=(
            "Optional custom OpenAI-compatible or Ollama base URL for local/self-hosted AI "
            "(e.g., 'http://localhost:11434/v1' for Ollama, 'http://localhost:8000/v1' for vLLM/SGLang, "
            "'http://localhost:1234/v1' for LM Studio, or 'https://models.github.ai/inference' for GitHub Models)."
        ),
    )
    llm_api_key: str | None = Field(
        default=None,
        description="Optional explicit API key override (defaults to GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, GITHUB_TOKEN, or 'local-no-key' for local servers).",
    )
    monty_timeout_ms: int = Field(
        default=2000,
        description="Execution timeout in milliseconds for Pydantic Monty sandbox evaluations.",
    )
    strict_verification: bool = Field(
        default=True,
        description="Enforce ruff, ty, marimo check, Monty sandbox, and Pointblank gates.",
    )
    package_manager: Literal["uv", "pixi"] = Field(
        default="uv",
        description="Allowed package and environment manager (pip is strictly forbidden).",
    )

    def ensure_directories(self) -> None:
        """Create local and global memory directories if they do not exist."""
        self.local_memory_dir.mkdir(parents=True, exist_ok=True)
        self.global_memory_dir.mkdir(parents=True, exist_ok=True)

    def apply_llm_environment(self) -> dict[str, str]:
        """Configure runtime environment variables for Cloud APIs, Local/Self-Hosted LLMs, or GitHub Models."""
        import os

        model_str = self.default_llm_model.strip()
        mode = "deterministic_offline"
        resolved_url = self.llm_base_url or os.environ.get("OPENAI_BASE_URL") or os.environ.get("OLLAMA_BASE_URL") or ""

        if model_str.lower() == "offline":
            return {"mode": mode, "model": "offline", "endpoint": "none"}

        if model_str.startswith("ollama:"):
            mode = "local_self_hosted (Ollama)"
            resolved_url = resolved_url or "http://localhost:11434/v1"
            os.environ.setdefault("OLLAMA_BASE_URL", resolved_url)
            os.environ.setdefault("OLLAMA_API_KEY", self.llm_api_key or "ollama-local")
        elif self.llm_base_url:
            if "models.github.ai" in self.llm_base_url or "inference.ai.azure.com" in self.llm_base_url:
                mode = "github_copilot_models"
                os.environ["OPENAI_BASE_URL"] = self.llm_base_url
                gh_token = self.llm_api_key or os.environ.get("GITHUB_TOKEN") or os.environ.get("OPENAI_API_KEY")
                if gh_token:
                    os.environ["OPENAI_API_KEY"] = gh_token
            else:
                mode = "local_self_hosted (OpenAI-compatible: vLLM / LM Studio / llama.cpp)"
                os.environ["OPENAI_BASE_URL"] = self.llm_base_url
                os.environ.setdefault("OPENAI_API_KEY", self.llm_api_key or "local-no-key")
        elif any(os.environ.get(k) for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")):
            mode = "cloud_api"
        elif os.environ.get("GITHUB_TOKEN") and model_str.startswith("openai:"):
            mode = "github_copilot_models"
            resolved_url = "https://models.github.ai/inference"
            os.environ.setdefault("OPENAI_BASE_URL", resolved_url)
            os.environ.setdefault("OPENAI_API_KEY", os.environ["GITHUB_TOKEN"])

        return {
            "mode": mode,
            "model": model_str,
            "endpoint": resolved_url or "provider-default",
        }

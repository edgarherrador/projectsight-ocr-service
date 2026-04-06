"""
Configuration settings for the PDF to Markdown converter application.
Loads environment variables from .env file.
"""
import re
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Gemini API Configuration
    gemini_api_key: str
    gemini_model: str = "gemini-3.1-pro"
    gemini_fallback_models: str = "gemini-1.5-pro"
    system_prompt: str = "./prompts/system_prompt.prompty"

    # Database Configuration
    database_path: str = "./cache/pdf_cache.db"

    # API Configuration
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # Gradio Configuration
    gradio_host: str = "127.0.0.1"
    gradio_port: int = 7860

    # File Size Limit (in MB)
    max_file_size_mb: int = 5

    class Config:
        """Pydantic config."""

        env_file = ".env"
        case_sensitive = False

    def get_system_prompt_text(self) -> str:
        """Load system prompt content from file path configured in SYSTEM_PROMPT."""
        prompt_path = Path(self.system_prompt).expanduser()
        if not prompt_path.is_absolute():
            prompt_path = (Path.cwd() / prompt_path).resolve()

        if not prompt_path.exists():
            raise FileNotFoundError(
                f"System prompt file not found: {prompt_path}"
            )

        prompt_text = prompt_path.read_text(encoding="utf-8").strip()
        if not prompt_text:
            raise ValueError(f"System prompt file is empty: {prompt_path}")

        # Basic .prompty support: drop YAML frontmatter and keep the prompt body.
        if prompt_path.suffix.lower() == ".prompty":
            prompt_text = re.sub(
                r"^---\s*\n.*?\n---\s*\n",
                "",
                prompt_text,
                flags=re.DOTALL,
            ).strip()

        return prompt_text

    def get_candidate_models(self) -> list[str]:
        """Return primary model + fallback models as an ordered deduplicated list."""
        candidates: list[str] = []

        primary = self.gemini_model.strip()
        if primary:
            candidates.append(primary)

        if self.gemini_fallback_models:
            for model_name in self.gemini_fallback_models.split(","):
                cleaned = model_name.strip()
                if cleaned and cleaned not in candidates:
                    candidates.append(cleaned)

        return candidates


# Global settings instance
settings = Settings()

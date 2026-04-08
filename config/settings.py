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
    max_file_size_mb: int = 30

    # Benchmark Configuration
    benchmark_models: str = "gemini-3.1-pro-preview,gemini-2.5-pro"
    benchmark_disable_cache: bool = True
    benchmark_ignore_size_limit: bool = True
    benchmark_max_file_size_mb: int = 50
    # Format: model_name:input_per_1m:output_per_1m,model2:input_per_1m:output_per_1m
    benchmark_model_prices: str = ""

    # Judge Configuration
    judge_model: str = "gemini-3.1-pro"
    judge_enabled: bool = True
    judge_similarity_threshold: float = 0.95
    judge_only_new_documents: bool = True
    judge_sample_rate: float = 0.0

    class Config:
        """Pydantic config."""

        env_file = ".env"
        case_sensitive = False
        extra = "ignore"

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

    def get_benchmark_models(self) -> list[str]:
        """Return benchmark models as an ordered deduplicated list."""
        models: list[str] = []

        if self.benchmark_models:
            for model_name in self.benchmark_models.split(","):
                cleaned = model_name.strip()
                if cleaned and cleaned not in models:
                    models.append(cleaned)

        return models

    def get_benchmark_price_map(self) -> dict[str, dict[str, float]]:
        """
        Parse benchmark model prices from a compact string.

        Expected format:
            model_name:input_per_1m:output_per_1m,model2:input_per_1m:output_per_1m
        """
        price_map: dict[str, dict[str, float]] = {}

        if not self.benchmark_model_prices.strip():
            return price_map

        for raw_entry in self.benchmark_model_prices.split(","):
            entry = raw_entry.strip()
            if not entry:
                continue

            parts = [part.strip() for part in entry.split(":")]
            if len(parts) != 3:
                continue

            model_name, input_price_raw, output_price_raw = parts
            if model_name.startswith("models/"):
                model_name = model_name[len("models/") :]

            try:
                input_price = float(input_price_raw)
                output_price = float(output_price_raw)
            except ValueError:
                continue

            price_map[model_name] = {
                "input_per_1m": input_price,
                "output_per_1m": output_price,
            }

        return price_map


# Global settings instance
settings = Settings()

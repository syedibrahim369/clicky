"""Settings from linux/.env, overridable by real environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

DEFAULT_ENV_FILE_PATH = Path(__file__).resolve().parents[2] / ".env"


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    # Left out of repr so that printing or logging Settings can never expose the key.
    gemini_api_key: str = field(repr=False)
    gemini_model: str
    ollama_model: str
    whisper_model: str
    piper_voice: str


def load_settings(env_file_path: Path = DEFAULT_ENV_FILE_PATH) -> Settings:
    file_values = dotenv_values(env_file_path)

    def read_setting(setting_name: str, default_value: str) -> str:
        # An empty value means "not filled in", so it falls through to the default.
        return os.environ.get(setting_name) or file_values.get(setting_name) or default_value

    return Settings(
        llm_provider=read_setting("LLM_PROVIDER", "gemini"),
        gemini_api_key=read_setting("GEMINI_API_KEY", ""),
        gemini_model=read_setting("GEMINI_MODEL", "gemini-3.8-flash"),
        ollama_model=read_setting("OLLAMA_MODEL", "qwen3-vl:4b"),
        whisper_model=read_setting("WHISPER_MODEL", "base.en"),
        piper_voice=read_setting("PIPER_VOICE", "en_US-lessac-medium"),
    )

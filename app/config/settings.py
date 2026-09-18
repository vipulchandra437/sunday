from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env")


class Settings(BaseModel):
    openrouter_api_key: str = Field(default="")
    brave_api_key: str = Field(default="")
    ollama_base_url: str = Field(default="http://localhost:11434")
    database_url: str = Field(default="sqlite:///./sunday.db")
    langgraph_checkpoint_path: str | None = Field(default=None)
    log_level: str = Field(default="INFO")
    data_dir: Path = Field(default_factory=lambda: PROJECT_ROOT / "data")
    config_path: Path = Field(default_factory=lambda: PROJECT_ROOT / "config.yaml")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY", "").strip(),
            brave_api_key=os.getenv("BRAVE_API_KEY", "").strip(),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip(),
            database_url=os.getenv("DATABASE_URL", "sqlite:///./sunday.db").strip(),
            langgraph_checkpoint_path=os.getenv("LANGGRAPH_CHECKPOINT_PATH", "").strip() or None,
            log_level=os.getenv("LOG_LEVEL", "INFO").strip() or "INFO",
        )


class ProviderConfig(BaseModel):
    model: str = ""
    base_url: str = ""
    supports_tools: bool = True
    price_desc: str = ""
    data_handling: str = ""


class AppConfig(BaseModel):
    default_model_provider: str = "openrouter"
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    workspace_paths: list[str] = Field(default_factory=list)
    risk_thresholds: dict[str, object] = Field(default_factory=dict)
    tool_risks: dict[str, str] = Field(default_factory=dict)


def load_config(path: Path | None = None) -> AppConfig:
    import yaml

    path = path or Settings.from_env().config_path
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return AppConfig.model_validate(raw)
    return AppConfig()


settings = Settings.from_env()
config = load_config()
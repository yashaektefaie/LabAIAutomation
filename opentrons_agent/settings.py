from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
KNOWLEDGE_DIR = PACKAGE_DIR / "knowledge_docs"


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str = field(repr=False, default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    model: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"))
    max_tokens: int = 16384
    temperature: float = 0.0
    knowledge_dir: Path = KNOWLEDGE_DIR

    # Extended thinking budget (0 = disabled)
    thinking_budget: int = field(default_factory=lambda: int(os.environ.get("THINKING_BUDGET", "10000")))

    # Vertex AI settings
    vertex_project: str = field(default_factory=lambda: os.environ.get("VERTEX_PROJECT", ""))
    vertex_region: str = field(default_factory=lambda: os.environ.get("VERTEX_REGION", "us-east5"))

    @property
    def use_vertex(self) -> bool:
        return bool(self.vertex_project)


def get_settings() -> Settings:
    return Settings()

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).resolve().parent / "skills"


def _skill_cache_disabled() -> bool:
    """开发态：AI_SKILL_CACHE_DISABLED=1/true 时跳过 LRU，改 .md 后立即生效。"""
    return os.getenv("AI_SKILL_CACHE_DISABLED", "").strip().lower() in ("1", "true", "yes")


def _read_skill_file(name: str) -> str:
    if not name:
        return ""
    path = _SKILLS_DIR / f"{name}.md"
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.warning("skill file not found: %s", path)
        return ""
    except Exception as exc:
        logger.warning("failed to load skill file %s: %s", path, exc)
        return ""


@lru_cache(maxsize=64)
def _load_skill_cached(name: str) -> str:
    return _read_skill_file(name)


def load_skill(name: str) -> str:
    if _skill_cache_disabled():
        return _read_skill_file(name)
    return _load_skill_cached(name)


def load_skills(names: list[str]) -> str:
    parts: list[str] = []
    for name in names:
        content = load_skill(name)
        if content:
            parts.append(content)
    return "\n\n".join(parts).strip()

"""
Prompt Loader — loads and caches prompt configuration from backend/prompts/*.yaml.

Provides a module-level singleton `prompt_loader` with typed properties for each
prompt component. All modules that previously used hardcoded constants should
import from this loader instead.

Hot-reload support: call prompt_loader.load() or hit POST /api/prompts/reload
to pick up edits without restarting the server.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

# Resolve path relative to this file: backend/app/prompts/ → backend/prompts/
PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


class PromptLoader:
    """
    Thread-safe YAML prompt loader.

    All prompt YAML files in backend/prompts/ are loaded eagerly at import time
    and cached in memory. Call load() to reload from disk without restarting.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """(Re)load all prompt YAML files from disk."""
        try:
            import yaml
        except ImportError:
            log.error("prompt_loader.pyyaml_missing", note="pip install PyYAML")
            return

        with self._lock:
            data: dict[str, Any] = {}
            for path in sorted(PROMPTS_DIR.glob("*.yaml")):
                try:
                    with path.open(encoding="utf-8") as f:
                        data[path.stem] = yaml.safe_load(f) or {}
                except Exception as exc:
                    log.error("prompt_loader.file_error", file=path.name, error=str(exc))
            self._data = data
            log.info("prompt_loader.loaded", files=list(data.keys()))

    # ── Typed accessors ──────────────────────────────────────────────────────

    @property
    def length_instructions(self) -> dict[str, str]:
        """context_type → length instruction string."""
        with self._lock:
            return dict(self._data.get("length_instructions", {}))

    @property
    def holding_phrases(self) -> dict[str, list[str]]:
        """context_type → list of holding phrase strings."""
        with self._lock:
            return dict(self._data.get("holding_phrases", {}))

    @property
    def claude_routing_keywords(self) -> frozenset[str]:
        """Keywords in transcript that escalate routing to Claude."""
        with self._lock:
            kw = self._data.get("routing_keywords", {}).get("claude_routing_keywords", [])
            return frozenset(kw)

    @property
    def claude_context_types(self) -> frozenset[str]:
        """Context types that always route to Claude."""
        with self._lock:
            ct = self._data.get("routing_keywords", {}).get("claude_context_types", [])
            return frozenset(ct)

    @property
    def context_keywords(self) -> dict[str, list[str]]:
        """Full context_keywords dict (combat_triggers, directed_fragments, etc.)."""
        with self._lock:
            return dict(self._data.get("context_keywords", {}))

    @property
    def system_prompt_sections(self) -> dict[str, Any]:
        """Static system prompt section strings."""
        with self._lock:
            return dict(self._data.get("system_prompt_sections", {}))

    # ── Convenience helpers ──────────────────────────────────────────────────

    def get_length_instruction(self, context_type: str) -> str:
        instructions = self.length_instructions
        return instructions.get(context_type, instructions.get("default", "1–2 sentences."))

    def get_holding_phrase(self, context_type: str) -> str:
        """Return a random holding phrase for the given context type."""
        import random
        phrases = self.holding_phrases
        options = phrases.get(context_type, phrases.get("default", ["..."]))
        return random.choice(options) if options else "..."

    def get_context_keyword_set(self, key: str) -> frozenset[str]:
        """Return a named keyword list from context_keywords.yaml as a frozenset."""
        kw = self.context_keywords
        return frozenset(kw.get(key, []))


# Module-level singleton — imported by all modules that need prompt data
prompt_loader = PromptLoader()

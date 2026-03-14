"""
Prompts router — hot-reload endpoint for prompt YAML files.

Allows developers to edit backend/prompts/*.yaml and pick up changes
without restarting the server.
"""

from fastapi import APIRouter
from app.prompts.loader import prompt_loader, PROMPTS_DIR

router = APIRouter(prefix="/prompts", tags=["prompts"])


@router.post("/reload")
def reload_prompts():
    """Reload all prompt YAML files from disk."""
    prompt_loader.load()
    return {
        "status": "reloaded",
        "prompts_dir": str(PROMPTS_DIR),
        "loaded_files": list(prompt_loader._data.keys()),
    }


@router.get("/")
def list_prompts():
    """Return the currently loaded prompt data (for inspection/debugging)."""
    return {
        "prompts_dir": str(PROMPTS_DIR),
        "length_instructions": prompt_loader.length_instructions,
        "holding_phrases": prompt_loader.holding_phrases,
        "claude_context_types": sorted(prompt_loader.claude_context_types),
        "claude_routing_keywords": sorted(prompt_loader.claude_routing_keywords),
        "context_keywords": prompt_loader.context_keywords,
    }

"""
LLM Router — Hybrid Brain.

Routes LLM calls to either:
  • Ollama (llama3.1:8b) — fast, local, no API cost
  • Claude API (claude-haiku) — higher quality for emotional/complex moments

Routing logic (from plan.md §4.5):
  combat_turn, casual_roleplay, direct_question, party_debate → Ollama
  emotional_beat, backstory_call, npc_social, moral_dilemma    → Claude

Both clients degrade gracefully:
  - Ollama: returns stub if server not reachable
  - Claude: returns stub if API key missing or call fails

All I/O is blocking (designed to run in asyncio thread pool).
"""

from __future__ import annotations

import json
import structlog
from dataclasses import dataclass

from app.config import get_settings

log = structlog.get_logger()
settings = get_settings()

# ── Routing table ─────────────────────────────────────────────────────────────

CLAUDE_CONTEXT_TYPES = frozenset({
    "emotional_beat",
    "backstory_call",
    "npc_social",
    "moral_dilemma",
})

# Keywords in recent transcript that escalate routing to Claude
CLAUDE_ROUTING_KEYWORDS = frozenset({
    "backstory", "trauma", "betrayal", "forgive", "sacrifice", "regret",
    "childhood", "died", "loved", "swore", "oath", "memory", "dream",
    "fear", "family", "vow", "alone", "promised",
})


@dataclass
class LLMResponse:
    text: str
    route: str          # "ollama" | "claude" | "stub"
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    error: str = ""


def select_route(context_type: str, recent_transcript: str = "") -> str:
    """
    Return 'claude' or 'ollama' for the given context.

    Keyword escalation: if the recent transcript contains emotional keywords,
    route to Claude regardless of context_type.
    """
    lower = recent_transcript.lower()
    if any(kw in lower for kw in CLAUDE_ROUTING_KEYWORDS):
        return "claude"
    if context_type in CLAUDE_CONTEXT_TYPES:
        return "claude"
    return "ollama"


# ── Ollama client ─────────────────────────────────────────────────────────────

def call_ollama(
    system_prompt: str,
    user_message: str,
    model: str | None = None,
) -> LLMResponse:
    """
    Synchronous Ollama chat call.
    Returns a stub response if Ollama is unreachable.
    """
    import time
    model = model or settings.ollama_model
    t0 = time.monotonic()

    try:
        import urllib.request
        import urllib.error

        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ],
            "stream": False,
            "options": {
                "temperature": 0.85,
                "top_p": 0.9,
                "num_predict": 120,
            },
        }).encode()

        req = urllib.request.Request(
            f"{settings.ollama_base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=settings.ollama_timeout_s) as resp:
            body = json.loads(resp.read())

        text = body.get("message", {}).get("content", "").strip()
        latency = (time.monotonic() - t0) * 1000
        prompt_tok = body.get("prompt_eval_count", 0)
        completion_tok = body.get("eval_count", 0)

        log.debug(
            "llm.ollama_response",
            model=model,
            latency_ms=round(latency),
            tokens=completion_tok,
        )
        return LLMResponse(
            text=text,
            route="ollama",
            model=model,
            prompt_tokens=prompt_tok,
            completion_tokens=completion_tok,
            latency_ms=latency,
        )

    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        log.warning("llm.ollama_failed", error=str(e), latency_ms=round(latency))
        return LLMResponse(
            text="",
            route="stub",
            model=model,
            latency_ms=latency,
            error=str(e),
        )


# ── Claude client ─────────────────────────────────────────────────────────────

def call_claude(
    system_prompt: str,
    user_message: str,
    model: str | None = None,
) -> LLMResponse:
    """
    Synchronous Anthropic API call.
    Returns a stub response if API key is missing or call fails.
    """
    import time
    model = model or settings.claude_model
    t0 = time.monotonic()

    if not settings.anthropic_api_key:
        log.warning("llm.claude_no_api_key")
        return LLMResponse(
            text="",
            route="stub",
            model=model,
            error="no_api_key",
        )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        msg = client.messages.create(
            model=model,
            max_tokens=settings.claude_max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        text = msg.content[0].text.strip() if msg.content else ""
        latency = (time.monotonic() - t0) * 1000
        prompt_tok = msg.usage.input_tokens
        completion_tok = msg.usage.output_tokens

        log.debug(
            "llm.claude_response",
            model=model,
            latency_ms=round(latency),
            tokens=completion_tok,
        )
        return LLMResponse(
            text=text,
            route="claude",
            model=model,
            prompt_tokens=prompt_tok,
            completion_tokens=completion_tok,
            latency_ms=latency,
        )

    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        log.error("llm.claude_failed", error=str(e), latency_ms=round(latency))
        return LLMResponse(
            text="",
            route="stub",
            model=model,
            latency_ms=latency,
            error=str(e),
        )


# ── Unified call ──────────────────────────────────────────────────────────────

def call_llm(
    system_prompt: str,
    user_message: str,
    context_type: str,
    recent_transcript: str = "",
) -> LLMResponse:
    """
    Route to Ollama or Claude based on context_type and keyword escalation,
    then call the appropriate backend.
    """
    route = select_route(context_type, recent_transcript)
    if route == "claude":
        return call_claude(system_prompt, user_message)
    return call_ollama(system_prompt, user_message)

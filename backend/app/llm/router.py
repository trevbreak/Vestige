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

from contextlib import nullcontext

from app.config import get_settings
from app.prompts.loader import prompt_loader

log = structlog.get_logger()


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
    Keywords and context types are loaded from routing_keywords.yaml.
    """
    lower = recent_transcript.lower()
    if any(kw in lower for kw in prompt_loader.claude_routing_keywords):
        return "claude"
    if context_type in prompt_loader.claude_context_types:
        return "claude"
    return "ollama"


# ── Ollama client ─────────────────────────────────────────────────────────────

def call_ollama(
    system_prompt: str,
    user_message: str,
    model: str | None = None,
    num_predict: int = 120,
) -> LLMResponse:
    """
    Synchronous Ollama chat call.
    Returns a stub response if Ollama is unreachable.
    """
    import time
    _settings = get_settings()
    model = model or _settings.ollama_model
    t0 = time.monotonic()

    # Phase 8: OTel span for Phoenix tracing (no-op if Phoenix not configured)
    try:
        from app.tracing import get_tracer as _get_tracer
        _span_ctx = _get_tracer("vestige.ollama").start_as_current_span("ollama.chat")
    except Exception:
        _span_ctx = nullcontext()

    with _span_ctx as _span:
        def _set_attr(key: str, val) -> None:
            try:
                if _span and hasattr(_span, "set_attribute"):
                    _span.set_attribute(key, val)
            except Exception:
                pass

        _set_attr("llm.model", model)
        _set_attr("llm.system", system_prompt[:500])
        _set_attr("llm.user", user_message[:500])

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
                    "num_predict": num_predict,
                },
            }).encode()

            req = urllib.request.Request(
                f"{_settings.ollama_base_url}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=_settings.ollama_timeout_s) as resp:
                body = json.loads(resp.read())

            text = body.get("message", {}).get("content", "").strip()
            latency = (time.monotonic() - t0) * 1000
            prompt_tok = body.get("prompt_eval_count", 0)
            completion_tok = body.get("eval_count", 0)

            _set_attr("llm.response", text[:500])
            _set_attr("llm.latency_ms", round(latency))
            _set_attr("llm.completion_tokens", completion_tok)

            log.info(
                "llm.ollama_response",
                model=model,
                latency_ms=round(latency),
                prompt_tokens=prompt_tok,
                completion_tokens=completion_tok,
                response_preview=text[:120],
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
    _settings = get_settings()
    model = model or _settings.claude_model
    t0 = time.monotonic()

    if not _settings.anthropic_api_key:
        log.warning("llm.claude_no_api_key")
        return LLMResponse(
            text="",
            route="stub",
            model=model,
            error="no_api_key",
        )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=_settings.anthropic_api_key)

        msg = client.messages.create(
            model=model,
            max_tokens=_settings.claude_max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        text = msg.content[0].text.strip() if msg.content else ""
        latency = (time.monotonic() - t0) * 1000
        prompt_tok = msg.usage.input_tokens
        completion_tok = msg.usage.output_tokens

        log.info(
            "llm.claude_response",
            model=model,
            latency_ms=round(latency),
            prompt_tokens=prompt_tok,
            completion_tokens=completion_tok,
            response_preview=text[:120],
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
    keyword_escalated = (
        route == "claude"
        and context_type not in prompt_loader.claude_context_types
    )
    log.info(
        "llm.route_selected",
        context_type=context_type,
        route=route,
        keyword_escalated=keyword_escalated,
    )
    if route == "claude":
        return call_claude(system_prompt, user_message)
    return call_ollama(system_prompt, user_message)

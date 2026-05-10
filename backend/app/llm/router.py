"""
LLM Router — Hybrid Brain.

Routes LLM calls to either:
  • GPT-4o (gpt-4o) — fast, low-latency for combat/ambient/quick reactions
  • Claude Sonnet 4.6  — richer emotional/story moments with prompt caching

Routing logic:
  emotional_beat, backstory_call, npc_social, moral_dilemma → Claude
  combat_turn, tactical, quick_reaction, ambient, default    → GPT-4o

Keyword escalation: if the recent transcript contains emotional keywords,
route to Claude regardless of context_type (loaded from routing_keywords.yaml).

Both clients degrade gracefully — return stub LLMResponse on any failure.
"""

from __future__ import annotations

import json
import time
import structlog
from dataclasses import dataclass

from contextlib import nullcontext

from app.config import get_settings
from app.prompts.loader import prompt_loader

log = structlog.get_logger()


@dataclass
class LLMResponse:
    text: str
    route: str          # "gpt4o" | "claude" | "stub"
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    error: str = ""


def select_route(context_type: str, recent_transcript: str = "") -> str:
    """
    Return 'claude' or 'gpt4o' for the given context.

    Keyword escalation: if the recent transcript contains emotional keywords,
    route to Claude regardless of context_type.
    """
    lower = recent_transcript.lower()
    if any(kw in lower for kw in prompt_loader.claude_routing_keywords):
        return "claude"
    if context_type in prompt_loader.claude_context_types:
        return "claude"
    return "gpt4o"


# ── GPT-4o client ─────────────────────────────────────────────────────────────

def call_gpt4o(
    system_prompt: str,
    user_message: str,
    model: str | None = None,
) -> LLMResponse:
    """
    Synchronous OpenAI chat call via GPT-4o.
    Returns a stub response if API key is missing or call fails.
    """
    _settings = get_settings()
    model = model or _settings.gpt4o_model
    t0 = time.monotonic()

    if not _settings.openai_api_key:
        log.warning("llm.gpt4o_no_api_key")
        return LLMResponse(text="", route="stub", model=model, error="no_api_key")

    try:
        from openai import OpenAI
        client = OpenAI(api_key=_settings.openai_api_key)

        response = client.chat.completions.create(
            model=model,
            max_tokens=_settings.gpt4o_max_tokens,
            temperature=_settings.gpt4o_temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ],
        )

        text = (response.choices[0].message.content or "").strip()
        latency = (time.monotonic() - t0) * 1000
        usage = response.usage or type("U", (), {"prompt_tokens": 0, "completion_tokens": 0})()
        prompt_tok = getattr(usage, "prompt_tokens", 0)
        completion_tok = getattr(usage, "completion_tokens", 0)

        log.info(
            "llm.gpt4o_response",
            model=model,
            latency_ms=round(latency),
            prompt_tokens=prompt_tok,
            completion_tokens=completion_tok,
            response_preview=text[:120],
        )
        return LLMResponse(
            text=text,
            route="gpt4o",
            model=model,
            prompt_tokens=prompt_tok,
            completion_tokens=completion_tok,
            latency_ms=latency,
        )

    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        log.error("llm.gpt4o_failed", error=str(e), latency_ms=round(latency))
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
    Synchronous Anthropic API call with prompt caching.

    The system prompt is sent as a single cacheable block — Anthropic caches
    the prefix on first call (ephemeral TTL: 5 min) so repeated calls with
    the same static system content pay only the completion tokens.
    """
    _settings = get_settings()
    model = model or _settings.claude_model
    t0 = time.monotonic()

    if not _settings.anthropic_api_key:
        log.warning("llm.claude_no_api_key")
        return LLMResponse(text="", route="stub", model=model, error="no_api_key")

    # Phase 3: OTel span for Phoenix tracing (no-op if not configured)
    try:
        from app.tracing import get_tracer as _get_tracer
        _span_ctx = _get_tracer("vestige.claude").start_as_current_span("claude.chat")
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
            import anthropic
            client = anthropic.Anthropic(api_key=_settings.anthropic_api_key)

            msg = client.messages.create(
                model=model,
                max_tokens=_settings.claude_max_tokens,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_message}],
            )

            text = msg.content[0].text.strip() if msg.content else ""
            latency = (time.monotonic() - t0) * 1000
            prompt_tok = msg.usage.input_tokens
            completion_tok = msg.usage.output_tokens
            cache_read = getattr(msg.usage, "cache_read_input_tokens", 0) or 0
            cache_write = getattr(msg.usage, "cache_creation_input_tokens", 0) or 0

            _set_attr("llm.response", text[:500])
            _set_attr("llm.latency_ms", round(latency))
            _set_attr("llm.completion_tokens", completion_tok)
            _set_attr("llm.cache_read_tokens", cache_read)

            log.info(
                "llm.claude_response",
                model=model,
                latency_ms=round(latency),
                prompt_tokens=prompt_tok,
                completion_tokens=completion_tok,
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
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
    Route to GPT-4o or Claude based on context_type and keyword escalation.
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
    return call_gpt4o(system_prompt, user_message)


# ── Backward-compat stub ──────────────────────────────────────────────────────

def call_ollama(
    system_prompt: str,
    user_message: str,
    model: str | None = None,
    num_predict: int = 120,
) -> LLMResponse:
    """Deprecated — routes to GPT-4o. Kept so existing tests don't break."""
    log.warning("llm.call_ollama_deprecated", hint="use call_gpt4o or call_llm instead")
    return call_gpt4o(system_prompt, user_message, model=model)

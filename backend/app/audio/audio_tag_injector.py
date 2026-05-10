"""
Secondary LLM pass — injects ElevenLabs audio tags into avatar dialogue.

Runs only when the avatar's model preference is eleven_v3 (which natively
interprets inline tone and sound tags). Skipped entirely for eleven_flash_v2_5.

Tag vocabulary:
  Tone tags   (placed at sentence start, affect all following speech):
    [somber] [excited] [resolute] [amused] [whispering] [tense] [playful] [defiant]

  Sound tags  (placed inline where the sound naturally occurs):
    [laughing] [sighs] [clears throat] [grunt] [gasps]

Uses GPT-4o-mini (cheap, ~150ms) or falls back to Claude Haiku 4.5.
Returns the original text unchanged on any failure so TTS is never blocked.
"""

from __future__ import annotations

import asyncio
import structlog

log = structlog.get_logger()

_SYSTEM = """\
You inject ElevenLabs audio expression tags into D&D character dialogue.

TONE tags go at the start of a sentence and affect all speech that follows:
  [somber] [excited] [resolute] [amused] [whispering] [tense] [playful] [defiant]

SOUND tags go inline exactly where the sound occurs:
  [laughing] [sighs] [clears throat] [grunt] [gasps]

Rules:
- Only tag spoken dialogue — never action text or narration.
- Maximum 2 tone changes per response. Do not over-tag.
- Add sound tags only where they would genuinely occur in speech.
- If no tags are appropriate, return the text exactly as given.
- Return ONLY the (possibly tagged) text. No explanation, no JSON.
"""


async def inject_audio_tags(
    text: str,
    avatar_name: str,
    context_type: str,
) -> str:
    """
    Inject ElevenLabs tone/sound tags into avatar dialogue text.

    Returns the tagged text, or the original text if injection fails or is
    unnecessary. Never raises — failures are logged and swallowed.
    """
    if not text or not text.strip():
        return text

    user_msg = (
        f"Character: {avatar_name}\n"
        f"Context: {context_type}\n\n"
        f"{text}"
    )

    # Try GPT-4o-mini first (cheapest + fast)
    tagged = await _try_gpt4o_mini(user_msg)
    if tagged:
        log.debug(
            "audio_tag_injector.tagged",
            avatar=avatar_name,
            model="gpt-4o-mini",
            original_len=len(text),
            tagged_len=len(tagged),
        )
        return tagged

    # Fallback: Claude Haiku
    tagged = await _try_claude_haiku(user_msg)
    if tagged:
        log.debug(
            "audio_tag_injector.tagged",
            avatar=avatar_name,
            model="claude-haiku-4-5",
            original_len=len(text),
            tagged_len=len(tagged),
        )
        return tagged

    log.debug("audio_tag_injector.passthrough", avatar=avatar_name)
    return text


async def _try_gpt4o_mini(user_msg: str) -> str | None:
    try:
        from app.config import get_settings
        settings = get_settings()
        if not settings.openai_api_key:
            return None

        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=300,
                temperature=0.3,
            ),
        )
        tagged = result.choices[0].message.content or ""
        return tagged.strip() if tagged.strip() else None
    except Exception as e:
        log.warning("audio_tag_injector.gpt4o_mini_failed", error=str(e))
        return None


async def _try_claude_haiku(user_msg: str) -> str | None:
    try:
        from app.config import get_settings
        settings = get_settings()
        if not settings.anthropic_api_key:
            return None

        import anthropic

        loop = asyncio.get_running_loop()
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        result = await loop.run_in_executor(
            None,
            lambda: client.messages.create(
                model="claude-haiku-4-5-20251001",
                system=_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
                max_tokens=300,
            ),
        )
        tagged = result.content[0].text if result.content else ""
        return tagged.strip() if tagged.strip() else None
    except Exception as e:
        log.warning("audio_tag_injector.claude_haiku_failed", error=str(e))
        return None

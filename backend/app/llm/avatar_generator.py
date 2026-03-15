"""
Avatar Generator — LLM-driven personality prompt and voice selection.

Called at avatar creation/randomise time to produce:
  • personality_prompt  — 150-200 word first-person persona description
  • personality_archetype — introvert | extrovert | reactive | stoic
  • verbosity            — float 0.0–1.0
  • interrupts_often     — bool
  • voice_id             — Edge-TTS voice best matching the character

Also exposes a backfill function for existing avatars that were created
before Phase 8 and lack these fields.
"""

from __future__ import annotations

import json
import structlog

log = structlog.get_logger()

# ── Voice catalogue ────────────────────────────────────────────────────────────
# English accents suitable for a medieval/fantasy setting.
# Structured as {language_code: {voice_id: {label, gender}}} for future
# multi-language expansion.
VOICE_CATALOGUE: dict[str, dict[str, dict]] = {
    "en": {
        "en-GB-RyanNeural":   {"label": "British RP — Male",         "gender": "male"},
        "en-GB-SoniaNeural":  {"label": "British RP — Female",       "gender": "female"},
        "en-GB-LibbyNeural":  {"label": "British — Female (warm)",   "gender": "female"},
        "en-IE-ConnorNeural": {"label": "Irish — Male",              "gender": "male"},
        "en-IE-EmilyNeural":  {"label": "Irish — Female",            "gender": "female"},
        "en-GB-MaisieNeural": {"label": "British — Female (bright)", "gender": "female"},
        "cy-GB-NiaNeural":    {"label": "Welsh — Female",            "gender": "female"},
        "en-GB-ThomasNeural": {"label": "British — Male (warm)",     "gender": "male"},
    }
}

# Flat list for the LLM to choose from
_VOICE_OPTIONS_TEXT = "\n".join(
    f'  "{vid}": {info["label"]} ({info["gender"]})'
    for vid, info in VOICE_CATALOGUE["en"].items()
)

_GENERATOR_SYSTEM = f"""You are a D&D 5e character personality analyst. Output ONLY a valid JSON object — no markdown, no explanation.

Given a D&D character's details, produce:

1. personality_prompt: A 150-200 word FIRST-PERSON description written as the character's inner voice.
   Write as "I am..." — describe:
   - How they speak (rhythm, directness, warmth, humour, silences)
   - Whether they talk often or rarely
   - How they react emotionally and socially
   - Any distinctive accent flavour or speech pattern
   - How they feel about speaking up in a group
   This text will be injected directly into the character's LLM system prompt, so write
   it as if the character is describing themselves to guide their own responses.

2. personality_archetype: One of exactly:
   - "introvert"  — speaks mainly when spoken to or named
   - "extrovert"  — talks freely, jumps into conversations
   - "reactive"   — engages with questions and debate but not idle chatter
   - "stoic"      — speaks only when directly addressed, named, or in combat

3. verbosity: A float 0.0–1.0
   0.0 = almost never speaks unless forced
   0.5 = balanced, speaks when relevant
   1.0 = constant talker, rarely silent

4. interrupts_often: true if the character is bold enough to cut others off; false otherwise

5. voice_id: Choose the BEST matching voice from this list based on the character's race,
   class, personality, gender, and backstory:
{_VOICE_OPTIONS_TEXT}

Output ONLY this JSON shape:
{{
  "personality_prompt": "...",
  "personality_archetype": "...",
  "verbosity": 0.0,
  "interrupts_often": false,
  "voice_id": "..."
}}"""

_VALID_ARCHETYPES = frozenset({"introvert", "extrovert", "reactive", "stoic"})
_VALID_VOICE_IDS = frozenset(VOICE_CATALOGUE["en"].keys())


def generate_personality_data(avatar_data: dict) -> dict:
    """
    Call Ollama to generate personality_prompt, archetype, verbosity,
    interrupts_often, and voice_id for the given avatar data dict.

    Returns a dict with the five keys, or sensible defaults on failure.
    """
    from app.llm.router import call_ollama
    from app.config import get_settings

    settings = get_settings()

    user_msg = (
        f"Name: {avatar_data.get('name', 'Unknown')}, "
        f"{avatar_data.get('race', 'Human')} {avatar_data.get('char_class', 'Fighter')}\n"
        f"Alignment: {avatar_data.get('alignment', '')}\n"
        f"Personality traits: {avatar_data.get('personality_traits', '')}\n"
        f"Ideals: {avatar_data.get('ideals', '')} | "
        f"Bonds: {avatar_data.get('bonds', '')} | "
        f"Flaws: {avatar_data.get('flaws', '')}\n"
        f"Backstory: {avatar_data.get('backstory', '')}\n"
        f"Sentence style: {avatar_data.get('sentence_style', '')}\n"
        f"Verbal tics: {avatar_data.get('verbal_tics', '')}\n"
        "\nGenerate the personality JSON now."
    )

    try:
        resp = call_ollama(
            system_prompt=_GENERATOR_SYSTEM,
            user_message=user_msg,
            model=settings.ollama_model,
            num_predict=600,
        )

        if resp.route == "stub" or not resp.text:
            log.warning("avatar_generator.ollama_unavailable", name=avatar_data.get("name"))
            return _defaults(avatar_data)

        raw = resp.text.strip()
        # Strip think-blocks from reasoning models
        if "<think>" in raw:
            raw = raw.split("</think>", 1)[-1].strip()
        # Strip markdown fences
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw.rsplit("```", 1)[0]
        # Extract first JSON object
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            log.warning("avatar_generator.no_json", name=avatar_data.get("name"))
            return _defaults(avatar_data)

        data = json.loads(raw[start:end])

        # Validate and coerce
        result = {
            "personality_prompt": str(data.get("personality_prompt", "")).strip() or None,
            "personality_archetype": (
                data.get("personality_archetype", "extrovert")
                if data.get("personality_archetype") in _VALID_ARCHETYPES
                else "extrovert"
            ),
            "verbosity": max(0.0, min(float(data.get("verbosity", 0.5)), 1.0)),
            "interrupts_often": bool(data.get("interrupts_often", False)),
            "voice_id": (
                data.get("voice_id")
                if data.get("voice_id") in _VALID_VOICE_IDS
                else _fallback_voice(avatar_data)
            ),
        }

        log.info(
            "avatar_generator.done",
            name=avatar_data.get("name"),
            archetype=result["personality_archetype"],
            voice=result["voice_id"],
        )
        return result

    except Exception as exc:
        log.error("avatar_generator.failed", name=avatar_data.get("name"), error=str(exc))
        return _defaults(avatar_data)


def _defaults(avatar_data: dict) -> dict:
    """Sensible defaults when generation fails."""
    return {
        "personality_prompt": None,
        "personality_archetype": "extrovert",
        "verbosity": 0.5,
        "interrupts_often": False,
        "voice_id": _fallback_voice(avatar_data),
    }


def _fallback_voice(avatar_data: dict) -> str:
    """Pick a reasonable default voice based on the character's likely gender."""
    name = avatar_data.get("name", "").lower()
    char_class = avatar_data.get("char_class", "").lower()
    # Heuristic: certain classes skew male/female in default D&D names
    # Fall back to British RP male as a safe default
    return "en-GB-RyanNeural"

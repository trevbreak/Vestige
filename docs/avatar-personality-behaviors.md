# Avatar Personality Behaviors (Phase 8)

Each avatar carries a rich, LLM-generated personality description that governs **how they speak**, **when they choose to engage**, and **what voice they use**. This document describes the system.

---

## Personality Prompt

### What it is

A 150–200 word, first-person internal monologue describing the character's inner voice and social behavior. Written as *"I am…"*, covering:

- Voice texture and rhythm (clipped, rambling, hesitant, assertive)
- Humor style (dry wit, boisterous, none)
- How they feel about speaking up
- Emotional reactions and impulse control
- Social instincts (do they fill silence or let it breathe?)
- Speech quirks, accent flavor, verbal habits

### Example — Stoic Dwarf Fighter

> I am Thorek Ironveil, and words are tools, not comfort. I speak when there is something worth saying — a threat to name, a decision to make, a comrade to warn. My voice is low and measured, each sentence deliberate. Humor escapes me unless the situation is truly absurd. I do not fill silence; silence is my natural state. I watch others talk and wait for the moment that matters. If someone asks me directly, I answer with the minimum required. I rarely speculate aloud. I do not argue — I act. My loyalty runs deep and I will voice it once, plainly, and never again. I find emotional outbursts exhausting and will remove myself from them if I can.

### Example — Gregarious Bard

> I am Finnian Brightstring, and every moment without a story is a moment wasted. I talk because thinking aloud helps me think better, and also because the silence at a table feels like a challenge I must answer. My sentences tumble over each other, parenthetical and digressive. I laugh easily and loud. I ask questions I already know the answer to because I want to hear *your* version. I notice when someone is quiet and I will coax them, gently, into the light. Conflict makes me uncomfortable and I will joke my way around it unless someone I care about is threatened, at which point I become unexpectedly fierce. I use metaphors constantly. Some of them even make sense.

### How it is generated

At avatar creation time (or via the backfill endpoint), the system calls Ollama with the character's full card (name, race, class, alignment, traits, ideals, bonds, flaws, backstory) and asks it to produce the `personality_prompt`, `personality_archetype`, `verbosity`, `interrupts_often`, and `voice_id` fields in a single JSON response.

The prompt is stored in `Avatar.personality_prompt` and injected verbatim into the LLM system prompt under a `== CHARACTER PERSONA ==` section, replacing the sparse `personality_traits / ideals / bonds / flaws` labels.

Avatars without a personality prompt fall back to the legacy sparse fields — this preserves compatibility with avatars created before Phase 8.

### Editing

The personality prompt is exposed as an editable textarea in the avatar form. Developers can review the generated text and tweak it before saving. The generated prompt is a starting point, not a lock.

---

## Personality Archetypes

The `personality_archetype` field controls when an avatar *chooses* to speak. Four values are supported:

### `extrovert` (default)

Engages with most triggers. Ambient and social topics fire freely. Verbosity roll applies for ambient triggers — a high-verbosity extrovert talks constantly, a low-verbosity extrovert still joins in more than most.

### `introvert`

Only speaks when **directly addressed** (score ≥ threshold) or their name is mentioned. Does not respond to ambient conversation or general group questions. Verbosity roll still applies for borderline cases.

### `reactive`

Engages questions, debate, and combat reliably. Ambient silence or background chatter? Silent. Ask them something or put them in danger — they'll respond. Verbosity roll applied for reactive triggers.

### `stoic`

Strict: only speaks when their name is mentioned, they are directly addressed, or combat is active. Everything else is ignored. Zero verbosity roll — either the condition is met or it isn't.

---

## Verbosity

A float from `0.0` to `1.0` controlling how likely the avatar is to speak on ambient triggers.

| Value | Behavior |
|---|---|
| `0.0` | Never speaks unprompted (effectively mute unless directly addressed) |
| `0.3` | Rarely joins ambient conversation |
| `0.5` | Default — speaks about half the time |
| `0.8` | Joins most conversations |
| `1.0` | Never stays quiet when something could be said |

The verbosity roll is applied *after* the archetype gate — so a stoic avatar with `verbosity=1.0` still only speaks when directly addressed.

---

## Interrupts Often

A boolean (`interrupts_often`) that, when `True`, lowers the avatar's interrupt confidence threshold by 30%. This makes the avatar more likely to jump in before the human finishes speaking — useful for impulsive, socially dominant characters.

Characters with `interrupts_often=False` (default) wait for a natural pause or full sentence before engaging.

---

## Differentiated Voices (Edge-TTS)

Each avatar is automatically assigned a voice from the Edge-TTS catalogue at creation time. The LLM picks the best-matching voice given the character's race, class, personality, and gender.

### Available voices

| Voice ID | Label | Gender |
|---|---|---|
| `en-GB-RyanNeural` | British RP — Male | Male |
| `en-GB-SoniaNeural` | British RP — Female | Female |
| `en-GB-LibbyNeural` | British — Female (warm) | Female |
| `en-GB-OliverNeural` | British — Male (young) | Male |
| `en-IE-ConnorNeural` | Irish — Male | Male |
| `en-IE-EmilyNeural` | Irish — Female | Female |
| `en-GB-MaisieNeural` | British — Female (bright) | Female |
| `cy-GB-NiaNeural` | Welsh — Female | Female |

### TTS engine preference

`tts_engine_preference` controls which TTS engine is used per avatar:

| Value | Behavior |
|---|---|
| `auto` (default) | XTTS-v2 if speaker embedding loaded; Edge-TTS if `voice_id` set; XTTS-v2 default otherwise |
| `edge` | Always use Edge-TTS with the assigned `voice_id` |
| `xtts` | Always use XTTS-v2 (ignores `voice_id`) |

### Emotion → speech rate

Edge-TTS maps emotion tags to SSML rate modifiers so delivery reflects the character's state:

| Emotion | Rate adjustment |
|---|---|
| `urgently` | `+15%` (faster) |
| `tense` | `+5%` |
| `laughing` | `+10%` |
| `quietly` | `-10%` (slower) |
| `whispering` | `-15%` |
| `default` | no change |

---

## Conditional Holding Phrases ("Thinking Out Loud")

Holding phrases (e.g., *"Hmm, let me think on that…"*) are played while the LLM generates a response. In Phase 8 they are conditional:

- **High-importance contexts** (`direct_question`, `emotional_beat`, `backstory_call`, `moral_dilemma`): always played if `holding_phrase_chance > 0`
- **All other contexts**: played with probability `holding_phrase_chance`

`holding_phrase_chance` is a per-avatar float (0.0–1.0, default 0.5) set in the avatar form.

---

## Backfill Endpoint

Existing avatars created before Phase 8 can be backfilled with personality data:

```
POST /api/avatars/generate-personality
# Body: {} — regenerates all avatars missing personality_prompt
# Body: {"avatar_id": 3} — regenerates one specific avatar
```

This calls Ollama for each avatar and updates `personality_prompt`, `personality_archetype`, `verbosity`, `interrupts_often`, and `voice_id`.

---

## Configurable Prompts

All keyword lists and holding phrase text live in `backend/prompts/*.yaml` and can be edited without restarting the server. After editing, call:

```
POST /api/prompts/reload
```

This hot-reloads all YAML files atomically. Changes take effect on the next LLM call.

Files:
- `length_instructions.yaml` — per context-type length guidance injected into system prompt
- `holding_phrases.yaml` — phrases per context type
- `routing_keywords.yaml` — what triggers Claude vs Ollama routing
- `context_keywords.yaml` — combat triggers, DM hotwords, directed fragments
- `system_prompt_sections.yaml` — static response rule strings

---

## LLM Tracing (Arize Phoenix)

The backend automatically starts Arize Phoenix at `http://localhost:6006` on startup. Every LLM call (Claude and Ollama) is traced with:

- Full system prompt and user message
- Response text
- Latency and token counts
- Avatar ID and context type (as span attributes)

Phoenix provides a UI for inspecting traces, running evaluations, and annotating responses. No extra setup is required.

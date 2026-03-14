# 🐉 DnD AI Avatar System — Master Build Plan

> A locally-hosted web application that creates AI avatars to stand in for absent D&D players.  
> Avatars listen passively to the table, chime in naturally with in-character voice responses,  
> maintain persistent session memory, and play by 5e rules. All audio processing runs locally  
> on a 24GB NVIDIA GPU. The LLM brain is a hybrid: local Ollama for speed, Claude API for depth.

---

## 1\. Core Design Philosophy

### Why Cascade Pipelines Feel Robotic

A naive voice AI pipeline looks like this:

```
Mic → STT → wait for silence → LLM → TTS → Speaker
```

This is how Alexa and Siri work, and it is why they feel robotic even when fast. The problem  
is not latency — it is the complete absence of duplex conversational behaviour. The system must  
wait for a speaker to fully stop before it can react at all. It never says "mm" or "right" while  
you're talking. It never starts forming a thought before you finish. Even at sub-1-second response  
time, the rhythm is mechanical because it is turn-based.

Real people at a D&D table do not behave this way. They murmur agreement while someone else is  
speaking. They half-start a sentence and trail off. They react mid-story with "wait, seriously?"  
They speak in fragments. They have opinions about each other.

This system is designed to replicate that behaviour, not merely respond to text.

### The Two-Layer Architecture

Rather than replacing the cascade entirely (which would sacrifice reasoning quality — full-duplex  
7B models are not strong enough for complex D&D roleplay), this system uses two layers:

```
┌─────────────────────────────────────────────────────────────────────┐
│  LAYER 1 — PRESENCE LAYER (always-on, real-time, no LLM)           │
│                                                                     │
│  Handles: backchanneling while others speak, ambient reactions,     │
│  holding phrases while the Reasoning Layer generates.               │
│  Latency target: < 300ms. Template-based. No LLM calls.            │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ triggers on confidence threshold
┌──────────────────────────────────▼──────────────────────────────────┐
│  LAYER 2 — REASONING LAYER (triggered, deliberate)                 │
│                                                                     │
│  Handles: actual in-character dialogue, D&D decisions, roleplay,   │
│  combat moves. Uses Ollama for fast responses, Claude for depth.    │
│  Latency target: 800ms–4s. Acceptable because avatars visibly      │
│  "think" via the Presence Layer while generating.                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2\. Tech Stack

| Layer | Technology | Rationale |
| --- | --- | --- |
| **Frontend** | React + Vite | Component-driven, fast HMR, single shared browser tab |
| **Backend** | Python 3.12 + FastAPI | GPU model integration, async WebSocket support |
| **Transcription** | `faster-whisper` (large-v3, CUDA) | Best WER/speed on GPU; fully local |
| **VAD** | `silero-vad` | Lightweight, streaming-compatible voice activity detection |
| **TTS** | Coqui XTTS-v2 (CUDA) | Voice cloning per avatar; expressive; GPU-accelerated |
| **Local LLM** | Ollama + `llama3.1:8b` (Q4) | Fast combat + routine decisions; ~5-6GB VRAM |
| **Cloud LLM** | Anthropic Claude (`claude-sonnet-4-5`) | Complex roleplay, memory synthesis, session summaries |
| **Embeddings** | `sentence-transformers` (`all-MiniLM-L6-v2`) | Memory retrieval via vector similarity |
| **Vector search** | `sqlite-vec` | Embedded in SQLite; no separate vector DB needed |
| **Session DB** | SQLite + SQLAlchemy + Alembic | Lightweight, file-based, persistent memory |
| **Real-time comms** | FastAPI WebSockets | Push transcripts and audio to browser in real time |
| **Audio capture** | `sounddevice` + `pyaudio` | Mic input on Windows; USB conference mic recommended |

### GPU Memory Budget (24GB VRAM)

| Model | VRAM | Notes |
| --- | --- | --- |
| faster-whisper large-v3 | ~3 GB | Loaded persistently |
| Coqui XTTS-v2 | ~3–4 GB | Loaded persistently |
| Ollama llama3.1:8b Q4 | ~5–6 GB | Loaded persistently via Ollama |
| **Total** | **~12 GB** | ~12 GB headroom; all three models coexist with no swapping |

### Hardware Recommendation

The single highest-impact addition is a dedicated table microphone. A good room mic  
eliminates the majority of multi-speaker audio problems that software solutions can only  
partially address.

| Item | Purpose | Approx. Cost |
| --- | --- | --- |
| **USB conference mic** (e.g. Jabra Speak 510) | Omnidirectional table pickup, built-in echo cancellation | $100–$150 |
| OR **Boundary/PZM mic** | Flat on table surface; excellent clarity for tabletop use | $50–$120 |

---

## 3\. Full System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                       Windows PC (Server)                            │
│                                                                      │
│  ┌───────────────┐  ┌──────────┐  ┌──────────────────────────────┐  │
│  │ USB Conf. Mic │─▶│ AEC Gate │─▶│  Silero VAD (streaming)      │  │
│  │ (sounddevice) │  │          │  │  + Energy-based spkr select  │  │
│  └───────────────┘  └──────────┘  └──────────────┬───────────────┘  │
│                                                   │                  │
│                                   ┌───────────────▼───────────────┐  │
│                                   │  faster-whisper (CUDA)        │  │
│                                   │  + Backchannel Classifier     │  │
│                                   │  + Optional speaker diarize   │  │
│                                   └───────────────┬───────────────┘  │
│                                                   │                  │
│                              ┌────────────────────▼──────────────┐   │
│                              │         Context Engine            │   │
│                              │  • Trigger detection              │   │
│                              │  • Interrupt confidence scoring   │   │
│                              │  • Suppression + cooldowns        │   │
│                              │  • Response queue (priority)      │   │
│                              │  • Context type classification    │   │
│                              └────────────────────┬──────────────┘   │
│                                                   │                  │
│      ┌────────────────────────────────────────────▼──────────────┐   │
│      │                      LLM Router                           │   │
│      │  Ambient/backchannel → local template  (no LLM, <300ms)  │   │
│      │  Combat/routine      → Ollama           (~800ms–1.5s)     │   │
│      │  Roleplay/emotional  → Claude API        (~2–4s)          │   │
│      └────────────────────────────────────────────┬──────────────┘   │
│                                                   │                  │
│           ┌───────────────────────────────────────▼──────────────┐   │
│           │             Response Post-Processor                  │   │
│           │  • Length enforcer (context-type based)              │   │
│           │  • Markdown stripper (plain text for TTS)            │   │
│           │  • First-person enforcer                             │   │
│           │  • Emotion tag injector ([tense], [quietly], etc.)   │   │
│           │  • Random jitter delay (1.5–4s, simulates thinking)  │   │
│           └───────────────────────────────────────┬──────────────┘   │
│                                                   │                  │
│                    ┌──────────────────────────────▼──────────────┐   │
│                    │         Coqui XTTS-v2 (GPU TTS)             │   │
│                    │  Per-avatar cloned voice profiles           │   │
│                    │  Emotion tag conditioning                   │   │
│                    │  Backchannel clips (pre-generated, quiet)   │   │
│                    └──────────────────────────────┬──────────────┘   │
│                                                   │                  │
│              ┌────────────────────────────────────▼──────────────┐   │
│              │            Audio Output Manager                   │   │
│              │  • Enforces 1 avatar speaking at a time           │   │
│              │  • Priority cutoff (high-priority interrupts low) │   │
│              │  • Echo gate: blocks mic input during TTS play    │   │
│              │  • WebSocket stream: pushes audio to browser      │   │
│              └────────────────────────────────────┬──────────────┘   │
└───────────────────────────────────────────────────┼──────────────────┘
                                                    │ Local Network
                                    ┌───────────────▼──────────────┐
                                    │  Browser (any LAN device)    │
                                    │  React Frontend              │
                                    │  D&D-themed shared screen    │
                                    └──────────────────────────────┘
```

---

## 4\. Feature Specifications

### 4.1 Avatar Management

Each AI avatar represents one absent player's D&D character. Avatars are configured once and  
persist across sessions.

**Avatar Profile:**

*   Character name, race, class, subclass, level, background
*   Ability scores (STR, DEX, CON, INT, WIS, CHA) + modifiers
*   Saving throws, skill proficiencies
*   Spell slots, known spells, prepared spells
*   Equipment and inventory
*   Backstory (free text, seeded into system prompt)
*   Alignment (constrains all moral decisions)
*   Personality traits, ideals, bonds, flaws (D&D 5e fields)
*   **Sentence style descriptor** (e.g. "short declarative bursts", "trails off with ellipses")
*   **Verbal tics** (e.g. "often invokes their deity", "deflects with dark humor under stress")
*   **Never-say list** (phrases that break character for this avatar)
*   Voice profile: 30–60s audio sample → cloned XTTS-v2 speaker embedding
*   Avatar portrait image (displayed on shared table screen)

**Avatar Modes (DM-toggleable per session):**

*   **Active** — AI is listening and will chime in naturally
*   **Passive** — Character present but AI only responds to direct name address
*   **Absent** — Written out; AI fully suppressed for this session

---

### 4.2 Audio Input Pipeline

**Flow:**

1.  `sounddevice` streams audio from the USB conference mic
2.  **AEC Gate**: mic input is blocked while any avatar TTS is playing, plus 200ms acoustic  
    decay, preventing the AI from hearing and transcribing its own voice
3.  **Silero VAD**: detects speech onset/offset; segments audio on silence boundaries
4.  **Overlap detection**: if two speakers are detected simultaneously, buffer the segment and  
    transcribe the louder stream; mark mixed segments as `[overlap]`
5.  **faster-whisper (CUDA)**: transcribes each VAD segment with timestamps
6.  **Backchannel Classifier**: short utterances (≤4 words matching a backchannel vocabulary)  
    are tagged `type: backchannel` — they are logged but do NOT trigger the context engine
7.  Transcript pushed via WebSocket to the frontend (live caption display)
8.  Transcript appended to the Session Context Buffer

**AEC Gate:**

```python
class EchoGate:
    def __init__(self):
        self._gate_until: float = 0.0

    def on_tts_end(self):
        self._gate_until = time.time() + 0.2  # 200ms acoustic decay

    def should_transcribe(self) -> bool:
        return time.time() > self._gate_until
```

**Backchannel Classifier:**

```python
BACKCHANNEL_TOKENS = {
    "yeah", "yep", "uh huh", "mm", "hmm", "oh", "right", "okay",
    "wow", "really", "no way", "interesting", "huh", "sure", "got it",
    "nice", "cool", "makes sense", "I see", "go on", "and then", "wait"
}

def classify_utterance(text: str) -> str:
    """Returns 'backchannel' | 'statement'"""
    cleaned = text.strip().lower().rstrip(".,!")
    words = cleaned.split()
    if len(words) <= 4 and any(bc in cleaned for bc in BACKCHANNEL_TOKENS):
        return "backchannel"
    return "statement"
```

---

### 4.3 Context Engine

The Context Engine decides _when_ and _whether_ an avatar should respond, and what kind  
of response is appropriate.

**Step 1 — Interrupt Confidence Scoring**

Every incoming statement is scored before the context engine acts on it:

```python
def interrupt_confidence(transcript: str, avatar_name: str) -> float:
    score = 0.0
    if avatar_name.lower() in transcript.lower():
        score += 0.8   # Direct address
    if "?" in transcript:
        score += 0.3   # Question
    if any(w in transcript.lower() for w in
           ["what do you", "what does", "your character", "what about", "how do you"]):
        score += 0.4   # Character-directed prompt
    return min(score, 1.0)

# > 0.6  → full LLM response
# 0.3–0.6 → ambient holding phrase only (no LLM)
# < 0.3  → ignore (unless silence gap or combat trigger fires separately)
```

**Step 2 — Additional Triggers**

Even at low confidence, these independently elevate to a full response:

*   Avatar's name spoken within the last 60 seconds
*   Combat round detected (DM says "roll initiative", "what do you do", "your turn")
*   Silence gap: > `SILENCE_GAP_TRIGGER` seconds of no speech AND avatar is Active

**Step 3 — Context Type Classification**

```python
CONTEXT_TYPES = {
    "combat_turn":     {"max_sentences": 2, "route": "ollama"},
    "casual_roleplay": {"max_sentences": 2, "route": "ollama"},
    "party_debate":    {"max_sentences": 2, "route": "ollama"},
    "direct_question": {"max_sentences": 3, "route": "ollama"},
    "emotional_beat":  {"max_sentences": 5, "route": "claude"},
    "backstory_call":  {"max_sentences": 5, "route": "claude"},
    "npc_social":      {"max_sentences": 4, "route": "claude"},
    "moral_dilemma":   {"max_sentences": 4, "route": "claude"},
}
```

**Step 4 — Suppression Logic**

An avatar will NOT generate a response if:

*   A human player is currently speaking (VAD active)
*   Another avatar is currently speaking or within `AVATAR_COOLDOWN_SECONDS`
*   The same avatar spoke within `SELF_COOLDOWN_SECONDS`
*   The DM has said the hotword ("Hold", "Pause") in the last 30 seconds
*   The transcript is tagged `[overlap]` or `[inaudible]`
*   The AEC Gate is active

**Step 5 — Response Queue Priority**

```
PRIORITY 1: DM hotword → cancel all queued responses immediately
PRIORITY 2: Direct address (avatar's name spoken)
PRIORITY 3: General party prompt or direct question
PRIORITY 4: Combat turn trigger
PRIORITY 5: Passive silence reaction
```

Only 1 avatar speaks at a time. If Avatar A is speaking and a Priority 2+ arrives for Avatar B:

*   A is in first 20% of audio → cut off A, yield to B
*   A is past 20% → let A finish, then B speaks immediately after

---

### 4.4 Presence Layer — Making Avatars Feel Alive

This is what separates the system from a chatbot. When an avatar is Active and listening,  
it produces real-time audio that does not require an LLM call.

**Backchannels (while a human is speaking):**

Pre-generated XTTS-v2 audio clips played at ~60% volume during human speech:

```python
BACKCHANNEL_LIBRARY = {
    "neutral":    ["mm", "hmm", "yeah", "right", "uh huh"],
    "surprised":  ["oh!", "oh really?", "no way"],
    "agreeing":   ["yeah, exactly", "I think so too", "mm, that's true"],
    "uncertain":  ["hmm, maybe...", "I'm not sure", "could be..."],
    "engaged":    ["wait—", "go on", "and then what?"],
}

def should_produce_backchannel(seconds_since_last: float) -> bool:
    if seconds_since_last < 8.0:   # max once per 8–15 seconds of continuous speech
        return False
    return random.random() < 0.35  # 35% chance when eligible
```

Backchannels are pre-generated during avatar setup (`generate_backchannels.py`) and cached  
as audio clips — zero generation latency at playback time.

**Ambient Reactions (during dead air):**

When `SILENCE_GAP_TRIGGER` passes and the LLM has not yet responded, a holding phrase plays  
to eliminate dead air and signal that the avatar is thinking:

```python
AMBIENT_REACTIONS = {
    "combat_turn":     ["[tense] I'm working out my options..."],
    "casual_roleplay": ["[quietly] Give me a moment..."],
    "direct_question": ["Hmm, let me think on that..."],
    "default":         ["Hmm.", "Right...", "..."],
}
```

The full LLM response follows 1–3 seconds later as a continuation of this holding phrase.

---

### 4.5 LLM Router (Hybrid Brain)

**Routing table:**

| Situation | Route | Target Latency |
| --- | --- | --- |
| Ambient reaction / backchannel | Template only (no LLM) | \< 300ms |
| Combat action selection | Ollama (llama3.1:8b) | ~800ms–1.5s |
| Short in-character quips | Ollama | ~800ms–1.5s |
| Skill check decisions | Ollama | ~800ms–1.5s |
| Deep roleplay / emotional beats | Claude API | ~2–4s |
| Morally complex decisions | Claude API | ~2–4s |
| NPC negotiation / social encounters | Claude API | ~2–4s |
| Backstory callbacks | Claude API | ~2–4s |
| Post-session memory summarisation | Claude API | offline |

**Claude routing keywords** — any of these in the last 5 transcript lines triggers Claude:

```python
CLAUDE_ROUTING_KEYWORDS = [
    "backstory", "trauma", "betrayal", "forgive", "sacrifice", "regret",
    "childhood", "died", "loved", "swore", "oath", "memory", "dream",
    "fear", "family", "vow", "alone", "promised"
]
```

---

### 4.6 System Prompt Architecture

Every avatar response is built from a modular prompt assembled at runtime.

**Full prompt template:**

```
You are {CHARACTER_NAME}, a {RACE} {CLASS} (Level {LEVEL}).
Your player is absent tonight. Portray them faithfully.

== IDENTITY ANCHOR ==
Alignment: {ALIGNMENT}
Background: {BACKGROUND}
Core personality: {ONE_LINE_PERSONALITY}

== CHARACTER VOICE ==
Sentence style: {SENTENCE_STYLE}
Verbal habits: {VERBAL_TICS}
Never say: {AVOID_PHRASES}

== MECHANICAL STATE ==
Current HP: {HP}/{MAX_HP}
Spell slots remaining: {SPELL_SLOTS}
Active conditions: {CONDITIONS}
{COMBAT_ACTIONS_JSON if in combat}

== PARTY RELATIONSHIPS ==
{RELATIONSHIP_NOTES}     ← 2–3 sentences per party member, updated post-session

== RELEVANT MEMORY ==
{TOP_5_MEMORY_CHUNKS}    ← retrieved via vector similarity search

== CURRENT SITUATION ==
{LAST_30_LINES_OF_TRANSCRIPT}

== RESPONSE RULES (CRITICAL) ==
Output ONLY your character's spoken words and/or one attempted action.
• Default: 1–2 sentences. Err short. Never monologue.
• Combat: 1 sentence for action, 1 optional for flavour.
• Emotional beat: up to {MAX_SENTENCES} sentences only if this moment calls for it.
• Always first person: "I reach for my sword", NEVER "{CHARACTER_NAME} reaches..."
• No markdown. No asterisks. No parentheticals. Plain spoken text only.
• No meta-game. Only know what your character would know.
• NEVER narrate outcomes. That is the DM's job.
• NEVER speak as another character or the DM.
• Trailing off is allowed: "I could try the door, or... hmm."
• Reacting to a party member is allowed: "—right, or we just burn it down."
• Allowed emotion cues (prepend only): [quietly] [urgently] [laughing] [tense] [whispering]

CONTEXT TYPE: {CONTEXT_TYPE}
RESPONSE LENGTH: {LENGTH_INSTRUCTION}
```

**Why explicit NEVER rules matter:** Without hard prohibitions and negative examples, LLMs  
will routinely try to narrate world events, speak as the DM, or play other characters — confirmed  
by independent D&D AI builder experience and documented in multiple similar projects.

**Character voice differentiation — example personas:**

The goal is for each avatar to sound structurally different, not just have different traits.  
These are sentence structure templates:

```
THARINDEL (lawful good paladin):
  Sentence style: "Action first, then speech — 'I step forward. We mean you no harm.'"
  Verbal habits: "Never uses contractions in solemn moments. Occasionally invokes deity."
  Never say: "I guess, whatever, fine"

RIVEN (chaotic neutral rogue):
  Sentence style: "Speech first, action implied. Heavy ellipses. Deflects with dark humor."
  Verbal habits: "Heavy contractions. Trails off under pressure. Sarcastic when stressed."
  Never say: "Indeed, I shall, it is my duty"

ORIK (neutral good barbarian):
  Sentence style: "Short declarative sentences. 10 words maximum. Full stop."
  Verbal habits: "Speaks feelings through objects: 'My axe doesn't like this smell.'"
  Never say: "Furthermore, however, I would suggest that"
```

---

### 4.7 Response Post-Processor

Every LLM output passes through post-processing before TTS:

```python
class ResponsePostProcessor:
    def process(self, text: str, context_type: str, avatar: Avatar) -> ProcessedResponse:
        text = self._enforce_first_person(text, avatar.name)
        text = self._strip_markdown(text)        # remove **, *, _, #, bullets
        text = self._strip_stage_directions(text) # remove (laughs), *sighs*, etc.
        text = self._enforce_length(text, context_type)
        emotion_tag = self._extract_emotion_tag(text)
        delay = random.uniform(1.5, 4.0)         # jitter: prevents robotic timing
        return ProcessedResponse(text=text, emotion=emotion_tag, delay_seconds=delay)
```

**Why response jitter matters:** avatars that respond at a perfectly consistent speed after an  
identical pause are immediately identifiable as AI. A 1.5–4s random delay is the simplest  
technique for simulating natural thinking variation.

---

### 4.8 Inter-Avatar Social Dynamics

Real party members have opinions about each other. This is built in at two levels:

**Cross-avatar reference injection (25% probability):**

When Avatar B generates a response, if Avatar A spoke in the last 2 transcript exchanges,  
this optional line is appended to Avatar B's prompt:

```
OPTIONAL: If it genuinely fits your character, briefly acknowledge what {AVATAR_A_NAME}
just said (agree, disagree, or build on it). Only do this if it feels natural — do not force it.
```

**Relationship notes (maintained in memory, injected every response):**

```
== PARTY RELATIONSHIPS ==
Orik: You saved him from the collapsing bridge in Session 3. He doesn't say it, but
you know he feels indebted. You find his bluntness refreshing.

Riven: You fundamentally disagree with her methods but respect her competence. You've
learned to give her space before questioning her decisions.
```

Short (2–3 sentences per party member), updated by Claude's post-session summarisation.

---

### 4.9 D&D 5e Rules Engine

A lightweight Python rules engine feeds legal action options to the LLM during combat,  
preventing mechanical hallucinations. Without tool-grounding, LLMs invent spells they  
don't have, use spent slots, and ignore conditions — confirmed by UCSD NeurIPS 2025 research.

**Covers:**

*   Action economy (Action, Bonus Action, Reaction, Movement per turn)
*   Spell slot tracking and recovery (short/long rest)
*   Concentration tracking (break on new concentration spell)
*   Available actions JSON — structured object fed to LLM during combat turns
*   Condition tracking (frightened, poisoned, stunned, incapacitated, etc.)
*   Death saving throw state
*   Advantage/disadvantage awareness

**Combat prompt injection:**

```
{
  "available_actions": {
    "action": ["Attack (longsword)", "Cast Spell", "Help", "Dodge", "Disengage"],
    "bonus_action": ["Second Wind (1/rest)"],
    "reaction": ["Shield of Faith (concentration active — would break)"],
    "movement": "30ft remaining"
  },
  "spell_slots": {"1st": 0, "2nd": 2, "3rd": 1},
  "concentration": "Bless (active on Riven and Orik)",
  "conditions": ["Frightened (source: vampire's gaze, save at start of turn)"],
  "current_hp": "38/52"
}
```

---

### 4.10 Session Memory System

**Memory categories:**

| Category | Examples |
| --- | --- |
| Story events | "The party discovered the lich's phylactery in Session 4" |
| NPC relationships | "Tharindel distrusts Guildmaster Voryn after the betrayal" |
| Items & resources | "Riven used her last 3rd-level slot", "Party has the Amulet of Proof" |
| Combat history | "Session 6: Party defeated the dragon, Kael knocked unconscious twice" |
| Party dynamics | "Mira and Orik have a running rivalry over tactics" |
| Character growth | "Riven levelled to 7 after Session 5, took Twinned Spell metamagic" |
| Relationship deltas | "Orik saved Tharindel from the pit trap — relationship warming" |

**Memory pipeline:**

1.  Raw session transcripts stored in full in SQLite
2.  **Mid-session compression**: every 60 minutes, Claude rolls up older transcript into a  
    compact summary — keeps the active context window lean and accurate
3.  **Post-session summarisation**: after DM clicks "End Session", Claude generates a  
    structured JSON update covering events, NPC attitudes, relationship changes, item changes
4.  DM reviews and approves/edits via `MemoryReview.jsx` before committing
5.  All entries embedded with `sentence-transformers` and stored with `sqlite-vec`
6.  Top-K relevant chunks retrieved per avatar response via cosine similarity

**Why mid-session compression is not optional:** LLM accuracy drops significantly as context  
grows. For 3+ hour sessions the raw transcript will exceed useful context by hour two.  
Validated by UCSD NeurIPS 2025 research on AI agents in extended D&D campaigns.

---

### 4.11 Shared Table UI (D&D Aesthetic)

A single browser tab on a shared screen. Accessible from any LAN device.

**Layout:**

```
┌──────────────────────────────────────────────────────────────────┐
│  🐉  PARTY OF THE IRON VALE  —  Session 7                       │
├──────────────────┬──────────────────────────────┬────────────────┤
│  AVATAR PANEL    │  LIVE TRANSCRIPT             │  SESSION LOG   │
│                  │                              │                │
│  ┌────────────┐  │  DM: "You enter the throne   │  📜 Session 7  │
│  │[Tharindel] │  │  room. The vampire lord      │  Key events    │
│  │ HP: 38/52  │  │  rises from his chair..."    │                │
│  │ 🎙Speaking │  │                              │  💀 Combat log │
│  └────────────┘  │  THARINDEL (AI):             │                │
│                  │  "I step forward, hand on    │  🎒 Items      │
│  ┌────────────┐  │  my holy symbol..."          │                │
│  │  [Orik]    │  │                              │  ❤ Relations   │
│  │ HP: 55/55  │  │  MIRA (Human): "Wait—let     │                │
│  │ ⏳Thinking │  │  me try to talk first"       │  📝 DM Notes   │
│  └────────────┘  │                              │                │
│                  │  ORIK (AI): [murmuring]      │                │
│  ┌────────────┐  │  "hmm..."                    │                │
│  │  [Riven]   │  │                              │                │
│  │ HP: 29/40  │  │                              │                │
│  │ 💤 Passive │  │                              │                │
│  └────────────┘  │                              │                │
├──────────────────┴──────────────────────────────┴────────────────┤
│  INITIATIVE: Tharindel (38) > Vampire (22) > Orik (17)           │
│  [End Session]  [Silence AI]  [DM Override]  [Settings]          │
└──────────────────────────────────────────────────────────────────┘
```

**Visual theme:**

*   Dark parchment background texture
*   Cinzel (headings) + IM Fell English (body) fonts
*   Amber/gold accents, deep crimson highlights
*   Avatar portraits in ornate SVG frame style
*   Animated candleflame pulse on the active/speaking avatar
*   Scroll-style session log panel with collapsible sections
*   Subtle floating ember particle effect background

**Avatar card status badges:**

*   🎙 Speaking — TTS audio playing
*   ⏳ Thinking — LLM generating (shows after holding phrase plays)
*   💬 Listening — Presence layer active; backchannel eligible
*   💤 Passive — DM has set to passive mode
*   ⬜ Absent — DM has set to absent mode

---

## 5\. Project File Structure

```
dnd-avatar-system/
├── backend/
│   ├── main.py                      # FastAPI app entry point
│   ├── config.py                    # All settings and constants
│   ├── audio/
│   │   ├── capture.py               # sounddevice mic streaming
│   │   ├── vad.py                   # silero-vad wrapper
│   │   ├── aec_gate.py              # Acoustic echo cancellation gate
│   │   ├── transcriber.py           # faster-whisper CUDA wrapper
│   │   ├── backchannel_classifier.py# True/false interruption classifier
│   │   ├── overlap_detector.py      # Multi-speaker overlap detection
│   │   └── tts.py                   # Coqui XTTS-v2 + voice profiles
│   ├── context/
│   │   ├── engine.py                # Main context engine orchestrator
│   │   ├── trigger_detector.py      # Trigger + confidence scoring
│   │   ├── suppressor.py            # Suppression + cooldown logic
│   │   ├── response_queue.py        # Priority queue manager
│   │   ├── context_classifier.py    # Context type classification
│   │   ├── memory.py                # SQLite memory read/write + vector search
│   │   └── rules_engine.py          # D&D 5e mechanical rules
│   ├── llm/
│   │   ├── router.py                # Routing logic: template / Ollama / Claude
│   │   ├── ollama_client.py         # Local LLM interface
│   │   ├── claude_client.py         # Anthropic API interface
│   │   ├── prompt_builder.py        # Modular prompt assembly
│   │   └── post_processor.py        # Length, markdown strip, jitter
│   ├── presence/
│   │   ├── layer.py                 # Presence layer orchestrator
│   │   ├── backchannel_player.py    # Pre-cached clip playback
│   │   └── ambient_reactions.py     # Holding phrase generator
│   ├── models/
│   │   ├── avatar.py                # Avatar SQLAlchemy model
│   │   ├── session.py               # Session + transcript models
│   │   ├── memory.py                # Memory entry + embedding models
│   │   └── character.py             # Full character sheet model
│   └── db/
│       ├── database.py              # DB init + connection
│       └── migrations/              # Alembic migrations
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components/
│   │   │   ├── AvatarCard.jsx       # Portrait, HP, status badge, animation
│   │   │   ├── LiveTranscript.jsx   # Auto-scroll, color-coded by speaker
│   │   │   ├── CombatTracker.jsx    # Initiative order, HP bars, conditions
│   │   │   ├── SessionLog.jsx       # Collapsible story/items/relations panels
│   │   │   ├── DMControls.jsx       # End session, silence, override, settings
│   │   │   └── MemoryReview.jsx     # Post-session DM review + edit UI
│   │   ├── hooks/
│   │   │   ├── useWebSocket.js      # WebSocket connection + message handling
│   │   │   └── useAudioPlayer.js    # Web Audio API playback queue
│   │   └── styles/
│   │       └── theme.css            # Parchment theme, fonts, animations
│   ├── public/
│   │   └── assets/                  # Fonts, textures, frame SVGs, particles
│   └── vite.config.js
├── voice_samples/                   # Avatar voice reference .wav files
├── data/
│   └── campaign.db                  # SQLite database (auto-created on first run)
├── scripts/
│   ├── setup_gpu.py                 # Verify CUDA, download all models
│   ├── clone_voice.py               # One-time voice cloning per avatar
│   ├── generate_backchannels.py     # Pre-generate backchannel audio clip library
│   └── import_character.py          # Import character sheet (manual or JSON)
├── .env                             # ANTHROPIC_API_KEY, MIC_DEVICE_INDEX
├── .env.example
├── requirements.txt
├── package.json
└── README.md
```

---

## 6\. Configuration Reference

```python
# backend/config.py

# ── LLM Routing ────────────────────────────────────────────────────────────
OLLAMA_MODEL = "llama3.1:8b"
CLAUDE_MODEL = "claude-sonnet-4-5"
CLAUDE_ROUTING_KEYWORDS = [
    "backstory", "trauma", "betrayal", "forgive", "sacrifice", "regret",
    "childhood", "died", "loved", "swore", "oath", "memory", "dream",
    "fear", "family", "vow", "alone", "promised"
]

# ── Audio Input ─────────────────────────────────────────────────────────────
MIC_DEVICE_INDEX    = 0      # Set to correct Windows audio device index
VAD_THRESHOLD       = 0.5    # Silero VAD sensitivity (0.0–1.0)
AEC_DECAY_MS        = 200    # Milliseconds to gate mic after TTS ends

# ── Trigger Timing ──────────────────────────────────────────────────────────
SILENCE_GAP_TRIGGER             = 4.0   # Seconds of silence before considering response
SELF_COOLDOWN_SECONDS           = 12    # Min gap before same avatar speaks again
AVATAR_COOLDOWN_SECONDS         = 3     # Min gap between any two avatars
INTERRUPT_CONFIDENCE_THRESHOLD  = 0.6   # Score required for full LLM response

# ── Response Naturalism ─────────────────────────────────────────────────────
RESPONSE_JITTER_MIN = 1.5   # Min seconds before response plays
RESPONSE_JITTER_MAX = 4.0   # Max seconds before response plays
BACKCHANNEL_MIN_GAP = 8.0   # Min seconds between backchannels from same avatar
BACKCHANNEL_CHANCE  = 0.35  # Probability of backchannel when eligible

# ── Memory ──────────────────────────────────────────────────────────────────
MEMORY_TOP_K              = 5    # Memory chunks retrieved per LLM call
TRANSCRIPT_CONTEXT_LINES  = 30   # Transcript lines included per prompt
MID_SESSION_COMPRESS_MINS = 60   # Roll up transcript every N minutes

# ── Network ─────────────────────────────────────────────────────────────────
HOST = "0.0.0.0"   # Bind to all interfaces for LAN access
PORT = 8000
```

---

## 7\. Build Phases

### Phase 1 — Foundation (Week 1–2)

*   FastAPI server scaffolding with WebSocket support
*   React + Vite frontend scaffolding
*   SQLite schema + SQLAlchemy models (avatar, session, transcript, memory)
*   Alembic migrations setup
*   Avatar CRUD UI (create/edit/delete with full character sheet fields)
*   Basic D&D-themed UI layout (static, no live audio)
*   Local network access verified (bind `0.0.0.0`, confirm from another LAN device)
*   `.env` config loading + settings panel stub

### Phase 2 — Voice Input Pipeline (Week 3–4)

*   `sounddevice` mic capture streaming to backend
*   `silero-vad` real-time voice activity detection
*   `faster-whisper` CUDA integration + transcript streaming to frontend
*   Live transcript display, color-coded by speaker
*   AEC Gate: mic blocking during TTS playback + 200ms decay
*   Backchannel Classifier: distinguish listening sounds from statements
*   Overlap detector: buffer + louder-speaker selection for simultaneous speech
*   `[overlap]` and `[inaudible]` transcript tagging

### Phase 3 — Voice Output Pipeline (Week 4–5)

*   Coqui XTTS-v2 CUDA integration
*   `clone_voice.py`: generate speaker embedding from 30–60s voice sample
*   Per-avatar voice profile storage (embedding + metadata in SQLite)
*   TTS audio streaming via WebSocket to browser
*   Web Audio API playback queue in frontend (`useAudioPlayer.js`)
*   Audio Output Manager: 1-at-a-time enforcement, priority cutoff
*   `generate_backchannels.py`: pre-generate 20–30 backchannel clips per avatar
*   Backchannel playback at 60% volume during human speech (Presence Layer)
*   Avatar card animated speaking indicator (candleflame pulse)
*   ⏳ Thinking badge + animated state during LLM generation

### Phase 4 — AI Brain (Week 5–6)

*   Ollama integration (llama3.1:8b)
*   Claude API integration
*   Context Engine: trigger detection + interrupt confidence scoring
*   Context Engine: suppression logic + cooldown timers
*   Context type classifier
*   LLM router (template / Ollama / Claude)
*   Modular prompt builder (all sections assembled at runtime)
*   Response Post-Processor (length, markdown strip, first-person, jitter)
*   Ambient reaction system (holding phrases on silence gap, no LLM)
*   Response queue with priority levels and cutoff logic
*   End-to-end: transcript → context engine → LLM → post-process → TTS → audio out

### Phase 5 — Memory System (Week 7–8)

*   Session transcript persistence (full text in SQLite)
*   Post-session Claude summarisation (structured JSON: events, NPCs, items, relationships)
*   `sentence-transformers` embedding pipeline
*   `sqlite-vec` vector similarity search
*   Top-K memory retrieval integrated into prompt builder
*   Mid-session context compression (rolling 60-minute Claude summaries)
*   `MemoryReview.jsx`: DM review/edit UI before memory commits
*   Relationship delta notes: updated post-session, injected into every prompt
*   Character sheet auto-update from session (HP, spell slots, items, level-ups)
*   Speaker attribution UI: tag "Speaker 0" → player name post-session

### Phase 6 — Rules Engine & Combat (Week 9–10)

*   D&D 5e action economy tracker (Action, Bonus Action, Reaction, Movement)
*   Spell slot tracking + short/long rest recovery
*   Concentration tracking (break on new concentration spell)
*   Condition tracker (frightened, poisoned, stunned, incapacitated, etc.)
*   Available actions JSON builder, fed to LLM during combat turns
*   Combat turn detection from transcript (DM speech pattern matching)
*   Initiative tracker UI component
*   Death saving throw state
*   Combat log in session log panel

### Phase 7 — Inter-Avatar Dynamics & Polish (Week 11–12)

*   Cross-avatar reference injection (25% chance on recent party speech)
*   Full D&D aesthetic: parchment texture, Cinzel/IM Fell fonts, candleflame animation
*   Avatar portrait upload + ornate SVG frame display
*   Floating ember particle effect background
*   DM hotword suppression ("Hold", "Pause")
*   Settings panel (all config values editable in UI, no restart needed)
*   End-to-end multi-avatar session test with 3 active avatars
*   GPU utilisation + latency profiling
*   README + setup guide

---

## 8\. Setup Instructions

1.  **Verify GPU**: `nvidia-smi` — confirm 24GB VRAM and CUDA 12.x
2.  **Clone repo**: `git clone <repo-url> && cd dnd-avatar-system`
3.  **Python environment**: `python -m venv venv && venv\Scripts\activate`
4.  **Install Python deps**: `pip install -r requirements.txt`
5.  **Install Ollama**: download from [ollama.com](https://ollama.com), then `ollama pull llama3.1:8b`
6.  **Download AI models**: `python scripts/setup_gpu.py`  
    _(downloads faster-whisper large-v3 and XTTS-v2 model weights)_
7.  **Configure**: copy `.env.example` → `.env`, set `ANTHROPIC_API_KEY` and `MIC_DEVICE_INDEX`
8.  **Install frontend deps**: `cd frontend && npm install`
9.  **Create avatars**: `python scripts/import_character.py` or via the web UI
10.  **Clone avatar voice**: `python scripts/clone_voice.py --avatar "Tharindel" --sample voice_samples/tharindel.wav`
11.  **Pre-generate backchannels**: `python scripts/generate_backchannels.py --avatar "Tharindel"`
12.  **Start server**: `python backend/main.py`
13.  **Access**: navigate to `http://<PC_LAN_IP>:8000` from any device on the local network

---

## 9\. Key Design Decisions

| Decision | Rationale |
| --- | --- |
| Two-layer architecture (Presence + Reasoning) | Full-duplex models lack the reasoning quality for D&D; cascade models lack listening behaviour. The two layers solve both problems independently. |
| Backchannel pre-generation | XTTS-v2 takes ~500ms even for short clips — too slow for real-time listening sounds. Pre-generation gives zero-latency playback. |
| Response jitter (1.5–4s random) | Fixed timing is immediately identifiable as AI. Jitter simulates natural thinking variation. |
| Holding phrases before LLM responses | Eliminates dead air during generation; sets the expectation that the avatar is "thinking" rather than lagging. |
| Context type → length mapping | Prevents LLM verbosity. Real players speak in fragments; the AI should too. |
| Mid-session context compression | LLM accuracy degrades significantly with long contexts. Validated by UCSD NeurIPS 2025 research on AI agents in extended D&D campaigns. |
| Hard NEVER rules + negative examples in prompts | Without explicit prohibitions, LLMs routinely try to narrate world events, speak as the DM, or play other characters. Confirmed across multiple independent D&D AI projects. |
| Claude for complex moments, Ollama for routine | Claude 3.5 Haiku outperformed GPT-4 and DeepSeek-V3 in D&D character consistency at NeurIPS 2025. Ollama handles the 80% of situations with lower latency and no API cost. |
| AEC timing gate (not full software AEC) | Full AEC is complex to tune correctly on Windows. Timing-based gating is simpler, reliable, and sufficient since TTS and mic are on the same machine. |
| SQLite + sqlite-vec | No separate infrastructure needed. Sufficient for 10+ campaigns and thousands of memory entries. |
| USB conference mic as primary recommendation | Software multi-speaker handling is inherently limited. Good hardware capture is the highest-leverage improvement to overall system quality. |

---

## 10\. Future Enhancements (Post-MVP)

*   **D&D Beyond import**: pull character sheets via D&D Beyond API or JSON export
*   **Pyannote diarization**: label individual speakers without per-person mics (V1.5 upgrade)
*   **PersonaPlex integration**: NVIDIA's open-source full-duplex model as a richer Presence Layer
*   **Per-speaker mics + USB mixer**: hardware solution for clean speaker separation
*   **Dice roll integration**: physical dice reader that feeds roll results to the context engine
*   **Campaign map overlay**: simple SVG map with avatar position markers on the shared screen
*   **Multi-campaign support**: separate SQLite databases with independent memory stores
*   **Mobile DM companion**: phone-optimised companion UI for DM session control
*   **Avatar emotional state tracking**: track avatar emotional state across the session and  
    modulate XTTS voice characteristics (rate, pitch) based on current emotional state
*   **Session replay**: play back a session with full audio + transcript in sync

---

## 11\. The Ten Most Important Lessons From Prior Art

Consolidated from: voice AI research (2024–2026), UCSD NeurIPS 2025 D&D research, NVIDIA  
PersonaPlex, Infobip D&D agentic engine, and independent D&D AI builder documentation.

**Cascade pipelines feel robotic regardless of speed** — the absence of listening behaviour is the core problem, not latency.

**Backchannelling while others speak is not optional** — "uh huh" and "hmm" are the primary signals that make an AI feel present rather than periodic.

**Without hard role boundaries, the AI will try to be the DM** — explicit NEVER rules with negative examples must be in every prompt.

**Brief responses always beat elaborate ones** — real players speak in fragments and trailing thoughts, not structured paragraphs.

**LLM accuracy degrades significantly over long sessions** — mid-session context compression is essential, not optional.

**Claude outperforms other models at in-character D&D consistency** — validated by NeurIPS 2025 research comparing Claude 3.5 Haiku, GPT-4, and DeepSeek-V3.

**Tool-grounding the rules engine prevents mechanical hallucinations** — the LLM must be fed legal options, not asked to generate them from memory.

**Echo cancellation is mandatory** — without it, the AI transcribes its own TTS audio and can respond to itself in a feedback loop.

**Plain text output must be explicitly required** — markdown produces audible noise in TTS ("asterisk asterisk I draw my asterisk asterisk sword").

**The table microphone matters more than any software feature** — good audio capture is the foundation everything else is built on.
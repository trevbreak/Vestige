#!/usr/bin/env python
"""
generate_backchannels.py — Pre-generate all backchannel audio clips for an avatar.

Backchannels are short utterances ("mm", "yeah", "right"...) that play at
~60% volume while humans are speaking. They must be pre-generated because
XTTS-v2 takes ~500ms per clip — too slow for real-time use.

Usage:
    python scripts/generate_backchannels.py --avatar-id 1
    python scripts/generate_backchannels.py --avatar-id 1 --device cpu

Output:
    data/backchannels/{avatar_id}/{category}/{text}.wav

Requirements:
    pip install TTS torch torchaudio numpy
    Also requires the avatar's speaker embedding at data/embeddings/{avatar_id}.npz
"""

import argparse
import sys
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "backend"))

# Import the backchannel library from the app
from app.presence.backchannel_player import BACKCHANNEL_LIBRARY


def text_to_filename(text: str) -> str:
    """Convert a backchannel text to a safe filename."""
    safe = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"\s+", "_", safe.strip())


def main():
    parser = argparse.ArgumentParser(description="Pre-generate backchannel clips for a Vestige avatar")
    parser.add_argument("--avatar-id", type=int, required=True)
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("--language", default="en")
    args = parser.parse_args()

    embedding_path = ROOT / "data" / "embeddings" / f"{args.avatar_id}.npz"
    if not embedding_path.exists():
        print(f"ERROR: No speaker embedding found at {embedding_path}")
        print(f"Run clone_voice.py --avatar-id {args.avatar_id} first.")
        sys.exit(1)

    output_base = ROOT / "data" / "backchannels" / str(args.avatar_id)

    print(f"Loading XTTS-v2 on {args.device}...")
    try:
        from TTS.api import TTS
        import torch
        import numpy as np

        tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(args.device)
        model = tts.synthesizer.tts_model

        # Load speaker embedding
        data = np.load(embedding_path, allow_pickle=True)
        gpt_cond_latent = torch.tensor(data["gpt_cond_latent"]).to(args.device)
        speaker_embedding = torch.tensor(data["speaker_embedding"]).to(args.device)

        total = sum(len(v) for v in BACKCHANNEL_LIBRARY.values())
        done = 0

        for category, texts in BACKCHANNEL_LIBRARY.items():
            cat_dir = output_base / category
            cat_dir.mkdir(parents=True, exist_ok=True)

            for text in texts:
                filename = text_to_filename(text) + ".wav"
                out_path = cat_dir / filename

                if out_path.exists():
                    print(f"  [skip] {category}/{filename}")
                    done += 1
                    continue

                print(f"  [{done+1}/{total}] Generating: '{text}' → {category}/{filename}")
                try:
                    out = model.inference(
                        text=text,
                        language=args.language,
                        gpt_cond_latent=gpt_cond_latent,
                        speaker_embedding=speaker_embedding,
                        speed=0.95,
                    )
                    # Save as WAV
                    import wave
                    import struct
                    import io

                    samples = np.array(out["wav"], dtype=np.float32)
                    samples_i16 = np.clip(samples * 32767, -32768, 32767).astype(np.int16)
                    sample_rate = 24000

                    with wave.open(str(out_path), "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(sample_rate)
                        wf.writeframes(samples_i16.tobytes())

                except Exception as e:
                    print(f"    ERROR generating '{text}': {e}")

                done += 1

        print()
        print(f"✓ Generated {done}/{total} backchannel clips")
        print(f"  Saved to: {output_base}")

    except ImportError as e:
        print(f"ERROR: Missing dependency — {e}")
        print("Install: pip install TTS torch torchaudio numpy")
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""
clone_voice.py — Generate a speaker embedding from a voice reference sample.

Usage:
    python scripts/clone_voice.py --avatar-id 1 --sample voice_samples/aldric.wav

Output:
    data/embeddings/{avatar_id}.npz  (gpt_cond_latent + speaker_embedding)

After running this, update the avatar's voice_embedding_path in the DB
(via the API PATCH /api/avatars/{id}) or start the server and it will
auto-load embeddings from data/embeddings/{avatar_id}.npz.

Requirements:
    pip install TTS torch torchaudio
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "backend"))


def main():
    parser = argparse.ArgumentParser(description="Clone a voice for a Vestige avatar")
    parser.add_argument("--avatar-id", type=int, required=True, help="Avatar ID in the database")
    parser.add_argument("--sample", type=str, required=True, help="Path to .wav reference file (30–60s)")
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    args = parser.parse_args()

    sample_path = Path(args.sample)
    if not sample_path.exists():
        print(f"ERROR: Voice sample not found: {sample_path}")
        sys.exit(1)

    output_dir = ROOT / "data" / "embeddings"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{args.avatar_id}.npz"

    print(f"Loading XTTS-v2 on {args.device}...")
    try:
        from TTS.api import TTS
        import torch
        import numpy as np

        tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(args.device)
        model = tts.synthesizer.tts_model

        print(f"Computing speaker embedding from: {sample_path}")
        gpt_cond_latent, speaker_embedding = model.get_conditioning_latents(
            audio_path=[str(sample_path)]
        )

        np.savez(
            output_path,
            gpt_cond_latent=gpt_cond_latent.cpu().numpy(),
            speaker_embedding=speaker_embedding.cpu().numpy(),
        )
        print(f"✓ Saved embedding to: {output_path}")
        print()
        print("Next steps:")
        print(f"  1. Update the avatar in the Vestige UI (or via API):")
        print(f"     PATCH /api/avatars/{args.avatar_id}")
        print(f"     {{ \"voice_embedding_path\": \"data/embeddings/{args.avatar_id}.npz\" }}")
        print(f"  2. Run generate_backchannels.py --avatar-id {args.avatar_id}")

    except ImportError as e:
        print(f"ERROR: Missing dependency — {e}")
        print("Install: pip install TTS torch torchaudio")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

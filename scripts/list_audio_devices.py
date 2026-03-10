#!/usr/bin/env python
"""List available audio input devices to find your MIC_DEVICE_INDEX."""

try:
    import sounddevice as sd
    devices = sd.query_devices()
    print("\nAvailable audio devices:")
    print("-" * 60)
    for i, d in enumerate(devices):
        marker = "  (default)" if i == sd.default.device[0] else ""
        if d["max_input_channels"] > 0:
            print(f"  [{i:2d}] IN  {d['name']}{marker}")
        if d["max_output_channels"] > 0:
            print(f"  [{i:2d}] OUT {d['name']}{marker}")
    print()
    print("Set MIC_DEVICE_INDEX in your .env to the number of your microphone.")
except ImportError:
    print("sounddevice not installed yet — it will be added in Phase 2.")
    print("Run: pip install sounddevice")

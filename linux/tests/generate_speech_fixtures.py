"""Writes spoken test clips and an index for verify_speech_x11.py.

    .venv/bin/python tests/generate_speech_fixtures.py <voices directory> <output directory>

Clips are synthetic, so they cover the pipeline and give a repeatable latency figure, but
they are cleaner than a real voice on a laptop microphone.
"""

import json
import sys
import wave
from pathlib import Path

from piper import PiperVoice

PHRASES = [
    "where's the wifi settings",
    "how do i change my wallpaper",
    "what does this button do",
    "open the bluetooth menu",
    "can you show me where the terminal is",
    "how do i turn on dark mode",
    "where can i find the display settings in gnome",
    "how do i connect to a vpn",
]
VOICE_NAMES = ["en_US-lessac-medium", "en_GB-alan-medium"]


def main():
    voices_directory = Path(sys.argv[1])
    output_directory = Path(sys.argv[2])
    output_directory.mkdir(parents=True, exist_ok=True)

    clip_index = []
    for voice_name in VOICE_NAMES:
        voice = PiperVoice.load(str(voices_directory / f"{voice_name}.onnx"))
        for phrase_number, phrase in enumerate(PHRASES):
            clip_path = output_directory / f"{voice_name}-{phrase_number}.wav"
            with wave.open(str(clip_path), "wb") as clip_file:
                voice.synthesize_wav(phrase, clip_file)
            clip_index.append({"file": str(clip_path), "text": phrase})

    (output_directory / "index.json").write_text(json.dumps(clip_index, indent=2))
    print(f"wrote {len(clip_index)} clips to {output_directory}")


if __name__ == "__main__":
    main()

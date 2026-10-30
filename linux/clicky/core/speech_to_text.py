"""Speech-to-text behind an interface, so providers can be swapped later."""

import threading
from typing import Protocol

import numpy

# Measured on an i7-1355U in linux/NOTES.md. More threads did not help, and these leave
# the rest of the CPU free for the overlay and a local LLM.
WHISPER_CPU_THREADS = 4
# Beam search adds about 0.15 s here, and stops words like "GNOME" being misheard.
WHISPER_BEAM_SIZE = 5
# Biases Whisper toward words a desktop question uses, like the contextual keyterms Clicky
# sends to AssemblyAI. Without it, "Bluetooth" came back as "blue cheese".
DESKTOP_VOCABULARY_HOTWORDS = "Wi-Fi, Bluetooth, GNOME, VPN, terminal, settings, wallpaper"


class SpeechToText(Protocol):
    def transcribe(self, audio_samples: numpy.ndarray) -> str:
        """Returns the text spoken in 16 kHz mono float32 samples, or "" for no speech."""
        ...


class FasterWhisperSpeechToText:
    def __init__(self, whisper_model_name: str):
        self.whisper_model_name = whisper_model_name
        self.whisper_model = None
        self.model_load_lock = threading.Lock()

    def load_model(self) -> None:
        """Loads the model, downloading it on first use. Safe to call more than once.

        Worth calling at startup in the background, or the first question pays for it.
        """
        with self.model_load_lock:
            if self.whisper_model is not None:
                return
            # Imported here because it takes seconds, and --trigger must stay instant.
            from faster_whisper import WhisperModel

            self.whisper_model = WhisperModel(
                self.whisper_model_name,
                device="cpu",
                compute_type="int8",
                cpu_threads=WHISPER_CPU_THREADS,
            )

    def transcribe(self, audio_samples: numpy.ndarray) -> str:
        self.load_model()
        transcript_segments, _ = self.whisper_model.transcribe(
            audio_samples,
            language="en",
            beam_size=WHISPER_BEAM_SIZE,
            # Without this, Whisper invents phrases such as "Thank you." from silence.
            vad_filter=True,
            condition_on_previous_text=False,
            hotwords=DESKTOP_VOCABULARY_HOTWORDS,
        )
        return " ".join(segment.text.strip() for segment in transcript_segments).strip()

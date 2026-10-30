"""Microphone recording. Audio stays in memory and is never written to disk."""

from typing import Protocol

import numpy
import sounddevice

# Whisper expects 16 kHz mono. The default device is PipeWire, which resamples from the
# hardware's 48 kHz for us, so there is no resampling code here.
RECORDING_SAMPLE_RATE = 16000


class AudioRecordingError(Exception):
    """Raised with a message suitable for showing to the user."""


class AudioRecorder(Protocol):
    def start(self) -> None:
        """Starts capturing. Raises AudioRecordingError if the microphone cannot open."""
        ...

    def stop(self) -> numpy.ndarray:
        """Stops capturing and returns mono float32 samples at RECORDING_SAMPLE_RATE."""
        ...


class MicrophoneRecorder:
    def __init__(self):
        self.input_stream: sounddevice.InputStream | None = None
        self.recorded_chunks: list[numpy.ndarray] = []

    def start(self) -> None:
        self.recorded_chunks = []
        try:
            self.input_stream = sounddevice.InputStream(
                samplerate=RECORDING_SAMPLE_RATE,
                channels=1,
                dtype="float32",
                callback=self.store_audio_chunk,
            )
            self.input_stream.start()
        except sounddevice.PortAudioError as port_audio_error:
            self.input_stream = None
            raise AudioRecordingError(f"Could not open the microphone: {port_audio_error}") from port_audio_error

    def store_audio_chunk(self, audio_chunk, frame_count, stream_time, stream_status) -> None:
        # PortAudio reuses this buffer after the callback returns, so it must be copied.
        self.recorded_chunks.append(audio_chunk.copy())

    def stop(self) -> numpy.ndarray:
        if self.input_stream is not None:
            self.input_stream.stop()
            self.input_stream.close()
            self.input_stream = None

        if not self.recorded_chunks:
            return numpy.zeros(0, dtype=numpy.float32)
        return numpy.concatenate(self.recorded_chunks).flatten()

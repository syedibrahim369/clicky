"""The state machine that runs one question: record, capture, then transcribe.

Trigger events arrive on background threads and must return quickly, so they only go
onto a queue. One thread works through that queue, and slow work such as transcription
runs on its own thread so that a new press can interrupt it.
"""

import queue
import threading
import time
from enum import Enum, auto
from typing import Callable

import numpy

from clicky.core.audio_capture import RECORDING_SAMPLE_RATE, AudioRecorder, AudioRecordingError
from clicky.core.speech_to_text import SpeechToText
from clicky.platform.base import CapturedScreen, Platform, TriggerEvent

# Stops a forgotten --trigger toggle, or a hold whose key release was lost to a virtual
# terminal switch, from recording forever.
MAXIMUM_RECORDING_SECONDS = 60.0
MINIMUM_AUDIO_SECONDS = 0.2


class OrchestratorState(Enum):
    IDLE = auto()
    RECORDING = auto()
    PROCESSING = auto()


class Orchestrator:
    def __init__(
        self,
        platform: Platform,
        audio_recorder: AudioRecorder,
        speech_to_text: SpeechToText,
        captured_screens_observer: Callable[[list[CapturedScreen]], None] | None = None,
        maximum_recording_seconds: float = MAXIMUM_RECORDING_SECONDS,
    ):
        self.platform = platform
        self.audio_recorder = audio_recorder
        self.speech_to_text = speech_to_text
        self.captured_screens_observer = captured_screens_observer
        self.maximum_recording_seconds = maximum_recording_seconds

        self.trigger_events: queue.Queue[TriggerEvent | None] = queue.Queue()
        self.state_lock = threading.Lock()
        self.state = OrchestratorState.IDLE
        self.recording_deadline = 0.0
        # A new press abandons in-flight work. That work cannot be killed, so it compares
        # its question number with this one and discards itself if it is out of date.
        self.current_question_number = 0
        self.event_thread = threading.Thread(target=self.process_trigger_events, daemon=True)

    def start(self) -> None:
        self.event_thread.start()

    def stop(self) -> None:
        self.trigger_events.put(None)
        self.event_thread.join(timeout=2.0)

    def handle_trigger_event(self, trigger_event: TriggerEvent) -> None:
        self.trigger_events.put(trigger_event)

    def process_trigger_events(self) -> None:
        while True:
            seconds_until_deadline = None
            if self.state == OrchestratorState.RECORDING:
                seconds_until_deadline = max(self.recording_deadline - time.monotonic(), 0.0)

            try:
                trigger_event = self.trigger_events.get(timeout=seconds_until_deadline)
            except queue.Empty:
                print(f"recording stopped at the {self.maximum_recording_seconds:.0f}s limit", flush=True)
                self.platform.end_active_trigger()
                self.finish_recording()
                continue

            if trigger_event is None:
                return
            if trigger_event == TriggerEvent.PRESSED:
                self.begin_recording()
            elif trigger_event == TriggerEvent.RELEASED:
                self.finish_recording()
            elif trigger_event == TriggerEvent.CANCELLED:
                self.discard_recording()

    def begin_recording(self) -> None:
        with self.state_lock:
            self.current_question_number += 1
            self.state = OrchestratorState.IDLE
        self.platform.clear()

        started_at = time.monotonic()
        try:
            self.audio_recorder.start()
        except AudioRecordingError as audio_recording_error:
            print(f"clicky: {audio_recording_error}", flush=True)
            self.platform.end_active_trigger()
            return

        print(f"listening (microphone opened in {time.monotonic() - started_at:.3f}s)", flush=True)
        with self.state_lock:
            self.state = OrchestratorState.RECORDING
            self.recording_deadline = time.monotonic() + self.maximum_recording_seconds

    def discard_recording(self) -> None:
        if self.state != OrchestratorState.RECORDING:
            return
        self.audio_recorder.stop()
        with self.state_lock:
            self.state = OrchestratorState.IDLE

    def finish_recording(self) -> None:
        # Late events are normal, for example the real release after the time limit.
        if self.state != OrchestratorState.RECORDING:
            return

        # The screenshot comes first because transcription is slow and the screen must be
        # the one the user was asking about. The microphone keeps running while it is
        # taken, which also protects the last word from a release that came slightly early.
        captured_screens = self.capture_screens()
        audio_samples = self.audio_recorder.stop()

        with self.state_lock:
            self.state = OrchestratorState.PROCESSING
            question_number = self.current_question_number

        threading.Thread(
            target=self.answer_question,
            args=(question_number, audio_samples, captured_screens),
            daemon=True,
        ).start()

    def capture_screens(self) -> list[CapturedScreen]:
        try:
            captured_screens = self.platform.capture()
        except Exception as capture_error:
            # Losing the screenshot should not lose what the user said.
            print(f"clicky: screen capture failed: {capture_error}", flush=True)
            return []
        if self.captured_screens_observer is not None:
            self.captured_screens_observer(captured_screens)
        return captured_screens

    def answer_question(
        self,
        question_number: int,
        audio_samples: numpy.ndarray,
        captured_screens: list[CapturedScreen],
    ) -> None:
        audio_seconds = len(audio_samples) / RECORDING_SAMPLE_RATE
        transcript = ""
        if audio_seconds >= MINIMUM_AUDIO_SECONDS:
            started_at = time.monotonic()
            try:
                transcript = self.speech_to_text.transcribe(audio_samples)
            except Exception as transcription_error:
                print(f"clicky: transcription failed: {transcription_error}", flush=True)
            print(
                f"timing: {audio_seconds:.2f}s of audio transcribed in"
                f" {time.monotonic() - started_at:.2f}s",
                flush=True,
            )

        with self.state_lock:
            if question_number != self.current_question_number:
                return
            self.state = OrchestratorState.IDLE

        print(f"heard: {transcript}" if transcript else "heard nothing", flush=True)

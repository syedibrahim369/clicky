import threading
import time

import numpy
import pytest

from clicky.core.audio_capture import RECORDING_SAMPLE_RATE, AudioRecordingError
from clicky.core.orchestrator import Orchestrator, OrchestratorState
from clicky.platform.base import TriggerEvent

WAIT_SECONDS = 2.0


class FakePlatform:
    def __init__(self, journal):
        self.journal = journal
        self.should_fail_capture = False
        self.end_active_trigger_call_count = 0

    def clear(self):
        self.journal.append("clear")

    def capture(self):
        self.journal.append("capture")
        if self.should_fail_capture:
            raise RuntimeError("no display")
        return ["screen"]

    def end_active_trigger(self):
        self.end_active_trigger_call_count += 1


class FakeRecorder:
    def __init__(self, journal, audio_seconds=1.0):
        self.journal = journal
        self.audio_seconds = audio_seconds
        self.should_fail_to_start = False

    def start(self):
        if self.should_fail_to_start:
            raise AudioRecordingError("no microphone")
        self.journal.append("record")

    def stop(self):
        self.journal.append("stop")
        return numpy.zeros(int(self.audio_seconds * RECORDING_SAMPLE_RATE), dtype=numpy.float32)


class FakeSpeechToText:
    """Blocks until released, so tests control exactly when transcription ends."""

    def __init__(self, journal, transcript="where's the wifi"):
        self.journal = journal
        self.transcript = transcript
        self.may_finish = threading.Event()
        self.may_finish.set()
        self.started = threading.Event()
        self.finished = threading.Event()

    def transcribe(self, audio_samples):
        self.journal.append("transcribe")
        self.started.set()
        self.may_finish.wait(WAIT_SECONDS)
        self.finished.set()
        return self.transcript


@pytest.fixture
def journal():
    return []


def build_orchestrator(journal, **orchestrator_arguments):
    platform = FakePlatform(journal)
    recorder = FakeRecorder(journal)
    speech_to_text = FakeSpeechToText(journal)
    orchestrator = Orchestrator(platform, recorder, speech_to_text, **orchestrator_arguments)
    orchestrator.start()
    return orchestrator, platform, recorder, speech_to_text


def wait_for_state(orchestrator, expected_state):
    for _ in range(200):
        if orchestrator.state == expected_state:
            return
        time.sleep(0.01)
    raise AssertionError(f"stuck in {orchestrator.state}, expected {expected_state}")


def test_order_is_record_then_screenshot_then_stop_then_transcribe(journal, capsys):
    orchestrator, _, _, speech_to_text = build_orchestrator(journal)
    orchestrator.handle_trigger_event(TriggerEvent.PRESSED)
    wait_for_state(orchestrator, OrchestratorState.RECORDING)
    orchestrator.handle_trigger_event(TriggerEvent.RELEASED)
    assert speech_to_text.finished.wait(WAIT_SECONDS)
    wait_for_state(orchestrator, OrchestratorState.IDLE)
    orchestrator.stop()
    assert journal == ["clear", "record", "capture", "stop", "transcribe"]
    assert "heard: where's the wifi" in capsys.readouterr().out


def test_cancel_discards_without_capture_or_transcription(journal):
    orchestrator, _, _, _ = build_orchestrator(journal)
    orchestrator.handle_trigger_event(TriggerEvent.PRESSED)
    wait_for_state(orchestrator, OrchestratorState.RECORDING)
    orchestrator.handle_trigger_event(TriggerEvent.CANCELLED)
    wait_for_state(orchestrator, OrchestratorState.IDLE)
    orchestrator.stop()
    assert journal == ["clear", "record", "stop"]


def test_recording_stops_itself_at_the_time_limit(journal, capsys):
    orchestrator, platform, _, speech_to_text = build_orchestrator(
        journal, maximum_recording_seconds=0.05
    )
    orchestrator.handle_trigger_event(TriggerEvent.PRESSED)
    assert speech_to_text.finished.wait(WAIT_SECONDS)
    wait_for_state(orchestrator, OrchestratorState.IDLE)
    orchestrator.stop()
    assert platform.end_active_trigger_call_count == 1
    assert "limit" in capsys.readouterr().out


def test_real_release_after_the_time_limit_is_ignored(journal):
    orchestrator, _, _, speech_to_text = build_orchestrator(journal, maximum_recording_seconds=0.05)
    orchestrator.handle_trigger_event(TriggerEvent.PRESSED)
    assert speech_to_text.finished.wait(WAIT_SECONDS)
    wait_for_state(orchestrator, OrchestratorState.IDLE)
    orchestrator.handle_trigger_event(TriggerEvent.RELEASED)
    orchestrator.stop()
    assert journal.count("transcribe") == 1


def test_new_press_abandons_the_transcription_in_progress(journal, capsys):
    orchestrator, _, _, speech_to_text = build_orchestrator(journal)
    speech_to_text.may_finish.clear()
    orchestrator.handle_trigger_event(TriggerEvent.PRESSED)
    wait_for_state(orchestrator, OrchestratorState.RECORDING)
    orchestrator.handle_trigger_event(TriggerEvent.RELEASED)
    assert speech_to_text.started.wait(WAIT_SECONDS)

    orchestrator.handle_trigger_event(TriggerEvent.PRESSED)
    wait_for_state(orchestrator, OrchestratorState.RECORDING)
    speech_to_text.may_finish.set()
    assert speech_to_text.finished.wait(WAIT_SECONDS)
    time.sleep(0.1)

    assert orchestrator.state == OrchestratorState.RECORDING
    orchestrator.handle_trigger_event(TriggerEvent.CANCELLED)
    orchestrator.stop()
    assert "heard:" not in capsys.readouterr().out


def test_microphone_failure_returns_to_idle_and_releases_the_trigger(journal, capsys):
    orchestrator, platform, recorder, _ = build_orchestrator(journal)
    recorder.should_fail_to_start = True
    orchestrator.handle_trigger_event(TriggerEvent.PRESSED)
    orchestrator.handle_trigger_event(TriggerEvent.RELEASED)
    orchestrator.stop()
    assert orchestrator.state == OrchestratorState.IDLE
    assert platform.end_active_trigger_call_count == 1
    assert "no microphone" in capsys.readouterr().out
    assert "transcribe" not in journal


def test_failed_capture_does_not_lose_the_question(journal, capsys):
    orchestrator, platform, _, speech_to_text = build_orchestrator(journal)
    platform.should_fail_capture = True
    orchestrator.handle_trigger_event(TriggerEvent.PRESSED)
    wait_for_state(orchestrator, OrchestratorState.RECORDING)
    orchestrator.handle_trigger_event(TriggerEvent.RELEASED)
    assert speech_to_text.finished.wait(WAIT_SECONDS)
    wait_for_state(orchestrator, OrchestratorState.IDLE)
    orchestrator.stop()
    assert "heard: where's the wifi" in capsys.readouterr().out


def test_extremely_short_audio_skips_transcription(journal, capsys):
    orchestrator, _, recorder, _ = build_orchestrator(journal)
    recorder.audio_seconds = 0.05
    orchestrator.handle_trigger_event(TriggerEvent.PRESSED)
    wait_for_state(orchestrator, OrchestratorState.RECORDING)
    orchestrator.handle_trigger_event(TriggerEvent.RELEASED)
    orchestrator.stop()
    time.sleep(0.1)
    assert "transcribe" not in journal
    assert "heard nothing" in capsys.readouterr().out

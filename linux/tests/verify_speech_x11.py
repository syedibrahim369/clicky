"""Integration check for M3, through the real app, hotkey and microphone stream.

    PYTHONPATH=<piper install> .venv/bin/python tests/generate_speech_fixtures.py <voices> <clips>
    scripts/dev-x11.sh
    DISPLAY=:20 PYTHONPATH=. .venv/bin/python tests/verify_speech_x11.py <clips directory>

Plays clips into a temporary virtual PipeWire microphone that only the app under test is
routed to, so the desktop's default microphone and speakers are never touched.
"""

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

VIRTUAL_SINK_NAME = "clicky_test_sink"
VIRTUAL_MICROPHONE_NAME = "clicky_test_mic"
SECONDS_BETWEEN_KEY_DOWN_AND_SPEECH = 0.2
TRANSCRIPT_TIMEOUT_SECONDS = 15.0


def start_virtual_microphone():
    return subprocess.Popen(
        [
            "pw-loopback", "-n", "clicky_test", "-c", "1",
            "--capture-props",
            f"media.class=Audio/Sink node.name={VIRTUAL_SINK_NAME} audio.position=[MONO]",
            "--playback-props",
            f"media.class=Audio/Source node.name={VIRTUAL_MICROPHONE_NAME} audio.position=[MONO]",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


class VoiceApp:
    def __init__(self):
        environment = dict(os.environ)
        # Routes this one process to the virtual microphone, leaving system defaults alone.
        environment["PIPEWIRE_ALSA"] = "{ target.object=" + VIRTUAL_MICROPHONE_NAME + " }"
        self.process = subprocess.Popen(
            [sys.executable, "-m", "clicky"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=environment,
        )
        self.output_lines = queue.Queue()
        threading.Thread(target=self.read_output, daemon=True).start()

    def read_output(self):
        for output_line in self.process.stdout:
            self.output_lines.put(output_line.strip())

    def wait_for_any(self, expected_prefixes, timeout_seconds=TRANSCRIPT_TIMEOUT_SECONDS):
        deadline = time.time() + timeout_seconds
        seen_lines = []
        while time.time() < deadline:
            try:
                output_line = self.output_lines.get(timeout=0.05)
            except queue.Empty:
                continue
            seen_lines.append(output_line)
            if output_line.startswith(tuple(expected_prefixes)):
                return output_line, seen_lines
        return None, seen_lines

    def peak_memory_megabytes(self):
        status_text = Path(f"/proc/{self.process.pid}/status").read_text()
        return int(re.search(r"VmHWM:\s+(\d+)", status_text).group(1)) // 1024

    def stop(self):
        self.process.terminate()
        self.process.wait(timeout=5)


def xdotool(*arguments):
    subprocess.run(["xdotool", *arguments], check=True)


def play_clip(clip_path):
    subprocess.run(["pw-play", f"--target={VIRTUAL_SINK_NAME}", clip_path], check=True)


def normalize_words(text):
    text = text.lower().replace("wi-fi", "wifi").replace("wi fi", "wifi")
    # The same question either way, and Whisper picks both spellings at random.
    text = text.replace("where's", "where is")
    return re.sub(r"[^a-z' ]", "", text).split()


def ask_with_hotkey(voice_app, clip_path, seconds_before_speech):
    xdotool("keydown", "ctrl", "keydown", "alt")
    time.sleep(seconds_before_speech)
    play_clip(clip_path)
    released_at = time.monotonic()
    xdotool("keyup", "alt", "keyup", "ctrl")
    heard_line, seen_lines = voice_app.wait_for_any(["heard"])
    return heard_line, seen_lines, time.monotonic() - released_at


def run_clips(voice_app, clips, seconds_before_speech):
    correct_count = 0
    response_seconds = []
    transcribe_seconds = []
    microphone_open_seconds = []
    for clip in clips:
        heard_line, seen_lines, seconds_after_release = ask_with_hotkey(
            voice_app, clip["file"], seconds_before_speech
        )
        heard_text = heard_line.removeprefix("heard:").strip() if heard_line else "(timed out)"
        is_correct = normalize_words(heard_text) == normalize_words(clip["text"])
        correct_count += is_correct
        response_seconds.append(seconds_after_release)
        for seen_line in seen_lines:
            if timing_match := re.search(r"transcribed in ([\d.]+)s", seen_line):
                transcribe_seconds.append(float(timing_match.group(1)))
            if open_match := re.search(r"opened in ([\d.]+)s", seen_line):
                microphone_open_seconds.append(float(open_match.group(1)))
        if not is_correct:
            print(f"   expected {clip['text']!r}, heard {heard_text!r}")
    return correct_count, response_seconds, transcribe_seconds, microphone_open_seconds


def mean(values):
    return sum(values) / len(values) if values else float("nan")


def main():
    clips_directory = Path(sys.argv[1])
    clips = json.loads((clips_directory / "index.json").read_text())
    results = {}

    virtual_microphone = start_virtual_microphone()
    time.sleep(1.0)
    voice_app = VoiceApp()
    try:
        started_at = time.monotonic()
        ready_line, seen_lines = voice_app.wait_for_any(["speech model ready"], timeout_seconds=30)
        results["speech model loads at startup"] = ready_line is not None
        print(f"model ready {time.monotonic() - started_at:.1f}s after launch")

        correct, responses, transcribes, opens = run_clips(
            voice_app, clips, SECONDS_BETWEEN_KEY_DOWN_AND_SPEECH
        )
        print(
            f"normal: {correct}/{len(clips)} exact, release-to-text mean {mean(responses):.2f}s"
            f" max {max(responses):.2f}s, transcribe mean {mean(transcribes):.2f}s,"
            f" mic open mean {mean(opens):.3f}s max {max(opens):.3f}s"
        )
        results["at least 14 of 16 clips are exact through the real pipeline"] = correct >= 14

        first_word_clips = clips[:8]
        correct, _, _, _ = run_clips(voice_app, first_word_clips, 0.0)
        print(f"speech starts the instant the key goes down: {correct}/{len(first_word_clips)} exact")
        results["first word survives speech starting on key-down"] = correct >= 6

        xdotool("keydown", "ctrl", "keydown", "alt")
        time.sleep(1.5)
        xdotool("keyup", "alt", "keyup", "ctrl")
        heard_line, _ = voice_app.wait_for_any(["heard"])
        print("silent hold:", heard_line)
        results["a silent hold invents nothing"] = heard_line == "heard nothing"

        subprocess.run([sys.executable, "-m", "clicky", "--trigger"], check=True, capture_output=True)
        time.sleep(0.2)
        play_clip(clips[0]["file"])
        subprocess.run([sys.executable, "-m", "clicky", "--trigger"], check=True, capture_output=True)
        heard_line, _ = voice_app.wait_for_any(["heard"])
        print("via --trigger:", heard_line)
        results["--trigger records and transcribes too"] = (
            heard_line is not None
            and normalize_words(heard_line.removeprefix("heard:")) == normalize_words(clips[0]["text"])
        )

        xdotool("keydown", "ctrl", "keydown", "alt")
        time.sleep(0.2)
        play_clip(clips[1]["file"])
        xdotool("keyup", "alt", "keyup", "ctrl")
        time.sleep(0.15)
        replacement_line, _, _ = ask_with_hotkey(voice_app, clips[2]["file"], 0.2)
        print("interrupted, then got:", replacement_line)
        results["a new press replaces the transcription in progress"] = (
            replacement_line is not None
            and normalize_words(replacement_line.removeprefix("heard:")) == normalize_words(clips[2]["text"])
        )

        print(f"app peak memory: {voice_app.peak_memory_megabytes()} MB")
    finally:
        voice_app.stop()
        virtual_microphone.terminate()
        virtual_microphone.wait(timeout=5)

    for description, passed in results.items():
        print(("PASS " if passed else "FAIL ") + description)
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())

"""Audio capture lifecycle and pause boundaries, independent of hardware setup."""

import queue
import threading
import time
import warnings
from contextlib import contextmanager
from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 16000


@dataclass(frozen=True)
class AudioChunk:
    generation: int
    start_sample: int
    audio: np.ndarray
    captured_at: float

    @property
    def end_sample(self):
        return self.start_sample + len(self.audio)


class PauseState:
    """Track transitions too, including a pause/resume during a slow operation."""

    def __init__(self):
        self._lock = threading.Lock()
        self._paused = False
        self._generation = 0

    def snapshot(self) -> tuple[bool, int]:
        with self._lock:
            return self._paused, self._generation

    def is_set(self) -> bool:
        return self.snapshot()[0]

    def set(self):
        self._update(True)

    def clear(self):
        self._update(False)

    def _update(self, paused):
        with self._lock:
            if self._paused != paused:
                self._paused = paused
                self._generation += 1

    def accepts(self, generation: int) -> bool:
        return self.snapshot() == (False, generation)


def drain_audio(audio_q):
    while True:
        try:
            audio_q.get_nowait()
        except queue.Empty:
            return


def _record_loop(mic, audio_q, stop_evt, pause_state, step_seconds):
    consecutive_errors = 0
    next_sample = 0
    while not stop_evt.is_set():
        paused, generation = pause_state.snapshot()
        start_sample = next_sample
        next_sample += SAMPLE_RATE * step_seconds
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                chunk = mic.record(numframes=SAMPLE_RATE * step_seconds)
            consecutive_errors = 0
            if stop_evt.is_set():
                return
            # Discard audio spanning either edge of a pause.
            if paused or not pause_state.accepts(generation):
                continue
            mono = (chunk.mean(axis=1) if chunk.ndim > 1 else chunk.flatten()).astype(np.float32)
            item = AudioChunk(generation, start_sample, mono, time.monotonic())
            try:
                audio_q.put_nowait(item)
            except queue.Full:
                try:
                    audio_q.get_nowait()
                except queue.Empty:
                    pass  # The consumer may have drained it since put_nowait.
                audio_q.put_nowait(item)
        except Exception as exc:
            consecutive_errors += 1
            if consecutive_errors == 1:
                print(f"[WARN] Audio capture error: {exc}")
            if consecutive_errors >= 5:
                print("[ERROR] Audio device lost, record thread exiting")
                return
            stop_evt.wait(0.5)


@contextmanager
def recording(mic, audio_q, pause_state, step_seconds):
    """Join the old reader before its recorder closes or a restart opens another."""
    capture_stop = threading.Event()
    thread = threading.Thread(
        target=_record_loop,
        args=(mic, audio_q, capture_stop, pause_state, step_seconds),
        name="audio-record", daemon=True,
    )
    thread.start()
    try:
        yield thread
    finally:
        capture_stop.set()
        thread.join()

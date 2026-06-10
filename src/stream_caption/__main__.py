"""
stream-caption entry point.
Captures system audio via WASAPI Loopback, transcribes Japanese speech with
faster-whisper, translates to Traditional Chinese with SakuraLLM, and
displays results in a floating tkinter overlay.

Usage: uv run stream-caption
"""

import difflib
import os
import queue
import threading
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np


def _find_cuda_bin() -> str | None:
    for env_var in ("CUDA_PATH", "CUDA_HOME"):
        p = os.environ.get(env_var)
        if p:
            bin_dir = Path(p) / "bin"
            if bin_dir.exists():
                return str(bin_dir)

    toolkit_root = Path(r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA")
    if toolkit_root.exists():
        for v in sorted(toolkit_root.iterdir(), reverse=True):
            bin_dir = v / "bin"
            if bin_dir.exists():
                return str(bin_dir)

    return None


_cuda_bin = _find_cuda_bin()
if _cuda_bin:
    os.add_dll_directory(_cuda_bin)

warnings.filterwarnings("ignore", message="data discontinuity", category=UserWarning)
import soundcard as sc
from faster_whisper import WhisperModel

from stream_caption.translator import translate
from stream_caption.overlay import SubtitleOverlay

SAMPLE_RATE = 16000
WINDOW_SECONDS = 4   # rolling transcription window size
STEP_SECONDS = 2     # record interval — 2s overlap prevents sentence cuts
SILENCE_THRESHOLD = 0.003
MIN_TEXT_LENGTH = 4

# Phrases Whisper commonly hallucinates on quiet/noisy segments
_HALLUCINATIONS = (
    "ご視聴ありがとうございました",
    "チャンネル登録",
    "字幕は自動生成",
    "ご視聴ありがとうございます",
    "お疲れ様でした",
)


def _is_hallucination(text: str) -> bool:
    return any(h in text for h in _HALLUCINATIONS)


def _is_duplicate(new: str, prev: str) -> bool:
    if not prev:
        return False
    return difflib.SequenceMatcher(None, new, prev).ratio() > 0.8


def load_model() -> WhisperModel:
    for device, compute in [("cuda", "float16"), ("cpu", "int8")]:
        try:
            print(f"Loading faster-whisper large-v3 ({device.upper()})...")
            start = time.time()
            model = WhisperModel("large-v3", device=device, compute_type=compute)
            print(f"Model loaded in {time.time() - start:.1f}s\n")
            return model
        except Exception as e:
            if device == "cpu":
                raise
            print(f"CUDA unavailable ({e}), falling back to CPU...")


def transcribe(model: WhisperModel, audio: np.ndarray, prev_text: str = "") -> str:
    segments, _ = model.transcribe(
        audio,
        language="ja",
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        initial_prompt=prev_text if prev_text else None,
    )
    return "".join(seg.text for seg in segments).strip()


def _record_loop(mic: sc.core.Recorder, audio_q: "queue.Queue[np.ndarray]") -> None:
    """Continuously capture audio chunks into the queue, independent of processing speed."""
    while True:
        try:
            chunk = mic.record(numframes=SAMPLE_RATE * STEP_SECONDS)
            mono = (chunk.mean(axis=1) if chunk.ndim > 1 else chunk.flatten()).astype(np.float32)
            if audio_q.full():
                audio_q.get_nowait()  # drop oldest to avoid unbounded backlog
            audio_q.put_nowait(mono)
        except Exception as e:
            print(f"[WARN] Audio capture error, skipping: {e}")


def main():
    overlay = SubtitleOverlay()
    overlay.start()
    print("Subtitle overlay started. Double-click the window to close.\n")

    default_speaker = sc.default_speaker()
    print(f"Using speaker loopback: {default_speaker.name}")
    if _cuda_bin:
        print(f"CUDA bin: {_cuda_bin}")

    log_dir = Path(__file__).parent.parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    prev_ja = ""
    prev_zh = ""
    audio_chunks: list[np.ndarray] = []
    max_chunks = WINDOW_SECONDS // STEP_SECONDS  # 2 chunks of 2s = 4s window

    # queue holds at most max_chunks * 2 chunks to allow some backlog without growing forever
    audio_q: queue.Queue[np.ndarray] = queue.Queue(maxsize=max_chunks * 2)

    with sc.get_microphone(default_speaker.id, include_loopback=True).recorder(
        samplerate=SAMPLE_RATE
    ) as mic, open(log_path, "w", encoding="utf-8") as log_file:
        model = load_model()
        # Discard audio buffered during model loading
        mic.record(numframes=SAMPLE_RATE * WINDOW_SECONDS)

        threading.Thread(target=_record_loop, args=(mic, audio_q), daemon=True).start()

        print(f"Logging to: {log_path}")
        print("Listening... Press Ctrl+C to stop.\n")

        while True:
            mono = audio_q.get()

            audio_chunks.append(mono)
            if len(audio_chunks) > max_chunks:
                audio_chunks.pop(0)
            if len(audio_chunks) < max_chunks:
                continue

            window = np.concatenate(audio_chunks)

            if float(np.abs(window).mean()) < SILENCE_THRESHOLD:
                continue

            t0 = time.time()
            ja_text = transcribe(model, window, prev_text=prev_ja)
            stt_ms = (time.time() - t0) * 1000

            if not ja_text or len(ja_text) < MIN_TEXT_LENGTH:
                continue
            if _is_hallucination(ja_text) or _is_duplicate(ja_text, prev_ja):
                continue

            t1 = time.time()
            zh_text = translate(ja_text, context_ja=prev_ja, context_zh=prev_zh)
            tl_ms = (time.time() - t1) * 1000

            if not zh_text:
                continue

            prev_ja = ja_text
            prev_zh = zh_text

            line = f"[STT {stt_ms:.0f}ms] {ja_text}\n[TL  {tl_ms:.0f}ms] {zh_text}\n"
            print(line)
            log_file.write(line + "\n")
            log_file.flush()

            overlay.push(ja_text, zh_text)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")

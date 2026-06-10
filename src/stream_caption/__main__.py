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
from PIL import Image, ImageDraw
import pystray

from stream_caption.settings import load_settings
from stream_caption.translator import translate
from stream_caption.overlay import SubtitleOverlay

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



def _load_model() -> WhisperModel:
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


def _transcribe(model: WhisperModel, audio: np.ndarray, prev_text: str = "") -> str:
    segments, _ = model.transcribe(
        audio,
        language="ja",
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        initial_prompt=prev_text if prev_text else None,
        no_repeat_ngram_size=3,          # beam search: block repeating 3-grams
        compression_ratio_threshold=1.8, # default 2.4; discard repetitive output early
        log_prob_threshold=-0.8,         # default -1.0; skip low-confidence segments
        no_speech_prob_threshold=0.7,    # default 0.6; stricter no-speech filtering
    )
    return "".join(seg.text for seg in segments).strip()


def _record_loop(mic, audio_q: queue.Queue, stop_evt: threading.Event) -> None:
    sample_rate = 16000
    step_frames = sample_rate * 2
    while not stop_evt.is_set():
        try:
            chunk = mic.record(numframes=step_frames)
            mono = (chunk.mean(axis=1) if chunk.ndim > 1 else chunk.flatten()).astype(np.float32)
            if audio_q.full():
                audio_q.get_nowait()
            audio_q.put_nowait(mono)
        except Exception as e:
            print(f"[WARN] Audio capture error: {e}")


def _pipeline(settings, overlay, stop_evt: threading.Event, pause_evt: threading.Event) -> None:
    audio_cfg = settings.audio
    sample_rate = 16000
    max_chunks = audio_cfg.window_seconds // audio_cfg.step_seconds

    speaker = sc.default_speaker()
    if audio_cfg.device:
        match = next(
            (s for s in sc.all_speakers() if audio_cfg.device.lower() in s.name.lower()),
            None,
        )
        if match:
            speaker = match
    print(f"Using speaker loopback: {speaker.name}")
    if _cuda_bin:
        print(f"CUDA bin: {_cuda_bin}")

    log_dir = Path(__file__).parent.parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    audio_q: queue.Queue[np.ndarray] = queue.Queue(maxsize=max_chunks * 2)

    with sc.get_microphone(speaker.id, include_loopback=True).recorder(
        samplerate=sample_rate
    ) as mic, open(log_path, "w", encoding="utf-8") as log_file:
        model = _load_model()
        mic.record(numframes=sample_rate * audio_cfg.window_seconds)

        threading.Thread(
            target=_record_loop, args=(mic, audio_q, stop_evt), daemon=True
        ).start()

        print(f"Logging to: {log_path}")
        print("Listening... Right-click tray icon to Pause or Quit.\n")

        prev_ja = ""
        prev_zh = ""
        audio_chunks: list[np.ndarray] = []

        while not stop_evt.is_set():
            if pause_evt.is_set():
                time.sleep(0.2)
                continue

            try:
                mono = audio_q.get(timeout=1.0)
            except queue.Empty:
                continue

            audio_chunks.append(mono)
            if len(audio_chunks) > max_chunks:
                audio_chunks.pop(0)
            if len(audio_chunks) < max_chunks:
                continue

            window = np.concatenate(audio_chunks)
            if float(np.abs(window).mean()) < audio_cfg.silence_threshold:
                continue

            t0 = time.time()
            ja_text = _transcribe(model, window, prev_text=prev_ja)
            stt_ms = (time.time() - t0) * 1000

            if stt_ms > 5000:
                # STT took too long — audio buffer is now stale, flush it
                audio_chunks.clear()
                try:
                    while True:
                        audio_q.get_nowait()
                except queue.Empty:
                    pass
                print(f"[WARN] STT took {stt_ms:.0f}ms, flushed stale audio buffer")

            if not ja_text or len(ja_text) < audio_cfg.min_text_length:
                continue
            if len(ja_text) > 200:
                print(f"[WARN] STT output too long ({len(ja_text)} chars), skipping")
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


def _create_tray_icon(state: str = "active") -> Image.Image:
    colors = {
        "active": ("#FFD700", "#87CEEB"),
        "paused": ("#555555", "#555555"),
        "error":  ("#FF4444", "#FF4444"),
    }
    c1, c2 = colors.get(state, colors["active"])
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([2, 2, 62, 62], radius=12, fill="#1a1a1a")
    draw.rounded_rectangle([10, 18, 54, 28], radius=3, fill=c1)
    draw.rounded_rectangle([10, 34, 44, 44], radius=3, fill=c2)
    return img


def _pipeline_watchdog(settings, overlay, stop_evt: threading.Event, pause_evt: threading.Event, tray_ref: list) -> None:
    """Restart pipeline thread if it crashes, update tray tooltip to reflect state."""
    while not stop_evt.is_set():
        t = threading.Thread(
            target=_pipeline,
            args=(settings, overlay, stop_evt, pause_evt),
            daemon=True,
        )
        t.start()
        t.join()  # wait until pipeline exits (normal or crash)

        if stop_evt.is_set():
            break

        print("[WARN] Pipeline stopped unexpectedly, restarting in 3s...")
        if tray_ref[0]:
            tray_ref[0].icon = _create_tray_icon("error")
            tray_ref[0].title = "stream-caption (restarting...)"
        time.sleep(3)
        if tray_ref[0] and not pause_evt.is_set():
            tray_ref[0].icon = _create_tray_icon("active")
            tray_ref[0].title = "stream-caption"


def main():
    settings = load_settings()
    overlay = SubtitleOverlay(settings.overlay)
    overlay.start()

    stop_evt = threading.Event()
    pause_evt = threading.Event()
    tray_ref: list = [None]

    threading.Thread(
        target=_pipeline_watchdog,
        args=(settings, overlay, stop_evt, pause_evt, tray_ref),
        daemon=True,
    ).start()

    def on_quit(icon, item):
        stop_evt.set()
        icon.stop()

    def on_toggle_pause(icon, item):
        if pause_evt.is_set():
            pause_evt.clear()
            icon.icon = _create_tray_icon("active")
            icon.title = "stream-caption"
        else:
            pause_evt.set()
            icon.icon = _create_tray_icon("paused")
            icon.title = "stream-caption (paused)"

    def pause_label(item):
        return "Resume" if pause_evt.is_set() else "Pause"

    menu = pystray.Menu(
        pystray.MenuItem(pause_label, on_toggle_pause),
        pystray.MenuItem("Quit", on_quit),
    )

    tray = pystray.Icon("stream-caption", _create_tray_icon(), "stream-caption", menu)
    tray_ref[0] = tray
    print("Subtitle overlay started. Right-click the tray icon to Pause or Quit.\n")
    tray.run()


if __name__ == "__main__":
    main()

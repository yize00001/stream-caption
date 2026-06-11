"""
stream-caption entry point.
Captures system audio via WASAPI Loopback, transcribes Japanese speech with
faster-whisper, translates to Traditional Chinese with SakuraLLM, and
displays results in a floating tkinter overlay.

Usage: uv run stream-caption
"""

import contextlib
import difflib
import os
import queue
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np
from pynput import keyboard as _kb


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



def _is_model_cached(model_name: str) -> bool:
    safe = model_name.replace("/", "--")
    cache = Path.home() / ".cache" / "huggingface" / "hub" / f"models--Systran--faster-whisper-{safe}"
    return cache.exists()


_MODEL_SIZES = {
    "large-v3": "~3GB", "large-v2": "~3GB",
    "medium": "~1.5GB", "small": "~500MB", "base": "~150MB", "tiny": "~75MB",
}


def _detect_best_model() -> str:
    """Pick model based on available GPU VRAM. Falls back to medium for CPU."""
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            vram_mb = int(result.stdout.strip().splitlines()[0])
            if vram_mb >= 4000:
                return "large-v3"
            elif vram_mb >= 2000:
                return "medium"
            else:
                return "small"
    except Exception:
        pass
    return "medium"  # no GPU or nvidia-smi not found


def _load_model(model_name: str = "large-v3", tray_ref: list | None = None) -> WhisperModel:
    first_run = not _is_model_cached(model_name)
    size_hint = _MODEL_SIZES.get(model_name, "")
    if first_run:
        print("=" * 55)
        print(f"  First run: downloading {model_name} ({size_hint})")
        print("  This may take several minutes — please wait...")
        print("=" * 55)
        if tray_ref and tray_ref[0]:
            tray_ref[0].title = "stream-caption (downloading model...)"
    for device, compute in [("cuda", "float16"), ("cpu", "int8")]:
        try:
            print(f"Loading faster-whisper {model_name} ({device.upper()})...")
            start = time.time()
            model = WhisperModel(model_name, device=device, compute_type=compute)
            elapsed = time.time() - start
            print(f"")
            print(f"  ✓ Model ready ({device.upper()}, {elapsed:.1f}s)")
            print(f"")
            if tray_ref and tray_ref[0]:
                tray_ref[0].title = "stream-caption"
            return model
        except Exception as e:
            if device == "cpu":
                raise
            print(f"CUDA unavailable ({e}), falling back to CPU...")
            print("")
            print("  ⚠️  WARNING: No compatible GPU found — running in CPU mode")
            print("      STT will take 20–30s per segment, not suitable for live use.")
            print("      For real-time use, an NVIDIA GPU with ≥4GB VRAM is required.")
            print("")


def _transcribe(
    model: WhisperModel,
    audio: np.ndarray,
    source_lang: str = "auto",
    prev_text: str = "",
    vocab: list[str] | None = None,
    beam_size: int = 5,
) -> tuple[str, str]:
    """Returns (transcribed_text, detected_language_code)."""
    whisper_lang = None if source_lang == "auto" else source_lang.lower().split("-")[0]
    # Use hotwords for vocab (boosts recognition without hallucination risk)
    # Use initial_prompt only for previous sentence context
    hotwords = " ".join(vocab) if vocab else None
    prompt = prev_text or None
    segments, info = model.transcribe(
        audio,
        language=whisper_lang,
        beam_size=beam_size,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        initial_prompt=prompt,
        hotwords=hotwords,
        no_repeat_ngram_size=3,
        compression_ratio_threshold=1.8,
        log_prob_threshold=-0.8,
        no_speech_threshold=0.7,
    )
    return "".join(seg.text for seg in segments).strip(), info.language


def _record_loop(mic, audio_q: queue.Queue, stop_evt: threading.Event) -> None:
    import warnings
    sample_rate = 16000
    step_frames = sample_rate * 2
    consecutive_errors = 0
    while not stop_evt.is_set():
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                chunk = mic.record(numframes=step_frames)
            consecutive_errors = 0
            mono = (chunk.mean(axis=1) if chunk.ndim > 1 else chunk.flatten()).astype(np.float32)
            if audio_q.full():
                audio_q.get_nowait()
            audio_q.put_nowait(mono)
        except Exception as e:
            consecutive_errors += 1
            if consecutive_errors == 1:
                print(f"[WARN] Audio capture error: {e}")
            time.sleep(0.5)
            if consecutive_errors >= 5:
                print("[ERROR] Audio device lost, record thread exiting")
                return


def _pipeline(settings, overlay, stop_evt: threading.Event, pause_evt: threading.Event, tray_ref: list | None = None) -> None:
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
        else:
            print(f"[WARN] Audio device '{audio_cfg.device}' not found, using system default: {speaker.name}")
    print(f"Using speaker loopback: {speaker.name}")
    if _cuda_bin:
        print(f"CUDA bin: {_cuda_bin}")

    log_path = None
    if settings.log.enabled:
        log_dir = Path(__file__).parent.parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    audio_q: queue.Queue[np.ndarray] = queue.Queue(maxsize=max_chunks * 2)

    log_ctx = open(log_path, "w", encoding="utf-8") if log_path else contextlib.nullcontext()
    with sc.get_microphone(speaker.id, include_loopback=True).recorder(
        samplerate=sample_rate
    ) as mic, log_ctx as log_file:
        model_name = settings.stt.model
        if model_name == "auto":
            model_name = _detect_best_model()
            print(f"[INFO] Auto-detected model: {model_name}")
        model = _load_model(model_name=model_name, tray_ref=tray_ref)
        mic.record(numframes=sample_rate * audio_cfg.window_seconds)

        rec_thread = threading.Thread(
            target=_record_loop, args=(mic, audio_q, stop_evt), daemon=True
        )
        rec_thread.start()

        src = settings.translation.source_lang
        tgt = settings.translation.target_lang
        print(f"Translation: {src} → {tgt}")
        if log_path:
            print(f"Logging to: {log_path}")
        else:
            print("Logging disabled")
        print("Listening... Right-click tray icon to Pause or Quit.\n")

        prev_src = ""
        prev_tgt = ""
        audio_chunks: deque[np.ndarray] = deque(maxlen=max_chunks)

        while not stop_evt.is_set():
            if not rec_thread.is_alive():
                raise RuntimeError("Audio record thread died, triggering watchdog restart")

            if pause_evt.is_set():
                time.sleep(0.2)
                continue

            try:
                mono = audio_q.get(timeout=1.0)
            except queue.Empty:
                continue

            audio_chunks.append(mono)
            if len(audio_chunks) < max_chunks:
                continue

            window = np.concatenate(audio_chunks)
            if float(np.abs(window).mean()) < audio_cfg.silence_threshold:
                continue

            t0 = time.time()
            src_text, detected_lang = _transcribe(
                model, window,
                source_lang=src,
                prev_text=prev_src,
                vocab=settings.stt.vocab,
                beam_size=settings.stt.beam_size,
            )
            stt_ms = (time.time() - t0) * 1000

            if stt_ms > 5000:
                audio_chunks.clear()
                try:
                    while True:
                        audio_q.get_nowait()
                except queue.Empty:
                    pass
                print(f"[WARN] STT took {stt_ms:.0f}ms, flushed stale audio buffer")
                continue

            if not src_text or len(src_text) < audio_cfg.min_text_length:
                continue
            if len(src_text) > 200:
                print(f"[WARN] STT output too long ({len(src_text)} chars), skipping")
                continue
            if _is_hallucination(src_text) or _is_duplicate(src_text, prev_src):
                continue

            # For auto-detect, use detected language; otherwise use configured source
            effective_src = detected_lang if src == "auto" else src

            t1 = time.time()
            tgt_text = translate(
                src_text,
                source_lang=effective_src,
                target_lang=tgt,
                context_ja=prev_src if effective_src == "ja" else "",
                context_zh=prev_tgt if effective_src == "ja" else "",
            )
            tl_ms = (time.time() - t1) * 1000

            if not tgt_text:
                continue

            prev_src = src_text
            prev_tgt = tgt_text

            line = f"[STT {stt_ms:.0f}ms][{detected_lang}] {src_text}\n[TL  {tl_ms:.0f}ms] {tgt_text}\n"
            print(line)
            if log_file:
                log_file.write(line + "\n")
                log_file.flush()

            overlay.push(src_text, tgt_text)


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
            args=(settings, overlay, stop_evt, pause_evt, tray_ref),
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

    hotkey_str = settings.hotkey.toggle
    try:
        hotkey = _kb.HotKey(
            _kb.HotKey.parse(hotkey_str),
            overlay.toggle,
        )

        def _on_press(key):
            try:
                hotkey.press(listener.canonical(key))
            except Exception:
                pass

        def _on_release(key):
            try:
                hotkey.release(listener.canonical(key))
            except Exception:
                pass

        listener = _kb.Listener(on_press=_on_press, on_release=_on_release)
        listener.daemon = True
        listener.start()
        print(f"Hotkey: {hotkey_str} — toggle overlay visibility")
    except Exception as e:
        print(f"[WARN] Could not register hotkey '{hotkey_str}': {e}")

    tray = pystray.Icon("stream-caption", _create_tray_icon(), "stream-caption", menu)
    tray_ref[0] = tray
    print("Subtitle overlay started. Right-click the tray icon to Pause or Quit.\n")
    tray.run()


if __name__ == "__main__":
    main()

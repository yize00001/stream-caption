"""
stream-caption entry point.
Captures system audio via WASAPI Loopback, transcribes Japanese speech with
faster-whisper, translates to Traditional Chinese with SakuraLLM, and
displays results in a floating tkinter overlay.

Usage: uv run stream-caption
"""

import contextlib
import json
import math
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

from stream_caption.settings import SettingsError, load_settings
from stream_caption.audio import PauseState, drain_audio, recording
from stream_caption.overlay import SubtitleOverlay
from stream_caption.quality import (
    SpeechSegment, SpeechWord, Transcription, SegmentHistory, TranslationContext, sanitize_diagnostic,
)
from stream_caption.captions import CaptionAssembler, CaptionUpdate

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
    use_previous_text: bool = False,
    word_timestamps: bool = False,
) -> Transcription:
    """Retain segment timestamps and quality signals for filtering and diagnosis."""
    whisper_lang = None if source_lang == "auto" else source_lang.lower().split("-")[0]
    # Hotwords are hints, not a guarantee against hallucinations.
    hotwords = " ".join(vocab) if vocab else None
    prompt = (prev_text or None) if use_previous_text else None
    segments, info = model.transcribe(
        audio,
        language=whisper_lang,
        beam_size=beam_size,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        initial_prompt=prompt,
        condition_on_previous_text=use_previous_text,
        word_timestamps=word_timestamps,
        hotwords=hotwords,
        no_repeat_ngram_size=3,
        compression_ratio_threshold=1.8,
        log_prob_threshold=-0.8,
        no_speech_threshold=0.7,
    )
    return Transcription(
        tuple(SpeechSegment(seg.text, seg.start, seg.end, seg.avg_logprob,
                            seg.no_speech_prob, seg.compression_ratio,
                            tuple(SpeechWord(word.word, word.start, word.end, word.probability)
                                  for word in (getattr(seg, 'words', None) or ()))) for seg in segments),
        info.language, info.language_probability, info.duration_after_vad,
    )


def _diagnose(file, **record):
    if file is not None:
        file.write(json.dumps(sanitize_diagnostic({"time": datetime.now().isoformat(), **record}),
                              ensure_ascii=False, allow_nan=False) + "\n")
        file.flush()


def _pipeline(settings, overlay, stop_evt: threading.Event, pause_evt: PauseState, tray_ref: list | None = None) -> None:
    from stream_caption.translator import translate_detailed

    audio_cfg = settings.audio
    sample_rate = 16000
    max_chunks = audio_cfg.window_seconds // audio_cfg.step_seconds
    stabilize = settings.stt.stabilize_captions
    buffer_chunks = (math.ceil(max(audio_cfg.window_seconds, settings.stt.caption_buffer_seconds)
                               / audio_cfg.step_seconds) if stabilize else max_chunks)

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
    diagnostics_path = None
    if settings.log.enabled or settings.log.diagnostics_enabled:
        log_dir = Path(__file__).parent.parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        if settings.log.enabled:
            log_path = log_dir / f"{stamp}.log"
        if settings.log.diagnostics_enabled:
            diagnostics_path = log_dir / f"{stamp}.diagnostics.jsonl"

    audio_q = queue.Queue(maxsize=max_chunks * 2)

    # Open capture only once the model is ready, so startup cannot queue old audio.
    model_name = settings.stt.model
    if model_name == "auto":
        model_name = _detect_best_model()
        print(f"[INFO] Auto-detected model: {model_name}")
    model = _load_model(model_name=model_name, tray_ref=tray_ref)
    if stop_evt.is_set():
        return

    with contextlib.ExitStack() as resources:
        log_file = resources.enter_context(open(log_path, "w", encoding="utf-8")) if log_path else None
        diagnostics_file = (resources.enter_context(open(diagnostics_path, "w", encoding="utf-8"))
                            if diagnostics_path else None)
        mic = resources.enter_context(sc.get_microphone(speaker.id, include_loopback=True).recorder(
            samplerate=sample_rate))
        with recording(mic, audio_q, pause_evt, audio_cfg.step_seconds) as rec_thread:
            src = settings.translation.source_lang
            tgt = settings.translation.target_lang
            print(f"Translation: {src} → {tgt}")
            if log_path:
                print(f"Logging to: {log_path}")
            else:
                print("Logging disabled")
            if diagnostics_path:
                print(f"Diagnostics: {diagnostics_path}")
            print("Listening... Right-click tray icon to Pause or Quit.\n")

            generation = pause_evt.snapshot()[1]
            prev_src = ""
            context = TranslationContext(settings.translation)
            history = SegmentHistory()
            last_audio_end = None
            audio_chunks = deque(maxlen=buffer_chunks)
            assembler = CaptionAssembler(
                max_buffer_seconds=buffer_chunks * audio_cfg.step_seconds,
                silence_seconds=settings.stt.caption_silence_seconds,
                stability_passes=settings.stt.caption_stability_passes,
                min_text_length=audio_cfg.min_text_length,
            )
            caption_cache = {}

            def publish(updates, chunk, window_start, stt_ms):
                nonlocal prev_src
                for update in updates:
                    if stop_evt.is_set() or not pause_evt.accepts(generation):
                        return
                    context_source, context_target = context.get(update.language, chunk.captured_at)
                    cached = caption_cache.get(update.caption_id) if update.caption_id else None
                    reused = cached is not None and cached[0] == update.text
                    t1 = time.perf_counter()
                    translation = cached[1] if reused else translate_detailed(
                        update.text, source_lang=update.language, target_lang=tgt,
                        context_source=context_source, context_target=context_target,
                        model_type=settings.translation.model_type,
                        glossary_id=settings.translation.glossary_id,
                        topic_context=settings.translation.topic_context,
                    )
                    tl_ms = (time.perf_counter() - t1) * 1000
                    obsolete = stop_evt.is_set() or not pause_evt.accepts(generation)
                    _diagnose(diagnostics_file, event="translation",
                              status="obsolete" if obsolete else translation.status,
                              source_text=update.text, translated_text=translation.text,
                              source_lang=update.language, target_lang=tgt,
                              window_start_sample=window_start, window_end_sample=chunk.end_sample,
                              caption_id=update.caption_id, revision=update.revision,
                              final=update.final, caption_reason=update.reason, cache_reused=reused,
                              backend=translation.backend, errors=translation.errors,
                              stt_ms=stt_ms, translation_ms=tl_ms,
                              latest_chunk_age_ms=(time.monotonic() - chunk.captured_at) * 1000)
                    if obsolete:
                        return
                    prev_src = update.text
                    if update.caption_id:
                        caption_cache[update.caption_id] = (update.text, translation)
                    if update.final:
                        if translation.text:
                            context.add(update.text, translation.text, update.language, chunk.captured_at)
                        caption_cache.pop(update.caption_id, None)
                    tgt_text = translation.text or "[翻譯暫時不可用]"
                    revision_label = (f"[caption {update.caption_id} rev={update.revision} final={update.final}]"
                                      if update.caption_id else "")
                    line = (f"[STT {stt_ms:.0f}ms][{update.language}]{revision_label} {update.text}\n"
                            f"[TL  {tl_ms:.0f}ms][{translation.backend}] {tgt_text}\n")
                    print(line)
                    if log_file:
                        log_file.write(line + "\n")
                        log_file.flush()
                    if update.caption_id:
                        overlay.upsert(update.caption_id, update.text, tgt_text, final=update.final)
                    else:
                        overlay.push(update.text, tgt_text)

            def trim_sealed_audio():
                retain_from = assembler.retain_from_sample(audio_cfg.step_seconds)
                while len(audio_chunks) > 1 and audio_chunks[0].end_sample <= retain_from:
                    audio_chunks.popleft()

            while not stop_evt.is_set():
                if not rec_thread.is_alive():
                    raise RuntimeError("Audio record thread died, triggering watchdog restart")

                paused, current_generation = pause_evt.snapshot()
                if current_generation != generation:
                    generation = current_generation
                    audio_chunks.clear()
                    drain_audio(audio_q)
                    prev_src = ""
                    context.clear()
                    history.clear()
                    assembler.clear()
                    caption_cache.clear()
                    last_audio_end = None
                if paused:
                    stop_evt.wait(0.1)
                    continue

                try:
                    chunk = audio_q.get(timeout=0.2)
                except queue.Empty:
                    continue

                if chunk.generation != generation or not pause_evt.accepts(generation):
                    continue
                if last_audio_end is not None and chunk.start_sample != last_audio_end:
                    audio_chunks.clear()
                    context.clear()
                    history.clear()
                    assembler.clear()
                    caption_cache.clear()
                    prev_src = ""
                    _diagnose(diagnostics_file, event="audio_gap",
                              previous_end=last_audio_end, next_start=chunk.start_sample)
                last_audio_end = chunk.end_sample
                audio_chunks.append(chunk)
                if stabilize and not assembler.pending:
                    while len(audio_chunks) > max_chunks:
                        audio_chunks.popleft()
                if len(audio_chunks) < max_chunks:
                    continue

                window = np.concatenate([item.audio for item in audio_chunks])
                amplitude = float(np.abs(window).mean())
                if amplitude < audio_cfg.silence_threshold:
                    _diagnose(diagnostics_file, event="audio_window", status="below_volume",
                              amplitude=amplitude, window_start_sample=audio_chunks[0].start_sample,
                              window_end_sample=chunk.end_sample)
                    if stabilize:
                        publish(assembler.advance(chunk.end_sample / sample_rate), chunk,
                                audio_chunks[0].start_sample, 0)
                        trim_sealed_audio()
                    continue

                t0 = time.perf_counter()
                transcription = _transcribe(
                    model, window,
                    source_lang=src,
                    prev_text=prev_src if settings.stt.use_previous_text else "",
                    vocab=settings.stt.vocab,
                    beam_size=settings.stt.beam_size,
                    use_previous_text=settings.stt.use_previous_text,
                    word_timestamps=stabilize,
                )
                stt_ms = (time.perf_counter() - t0) * 1000
                window_start = audio_chunks[0].start_sample
                quality_segments = []
                decisions = []
                for segment in transcription.segments:
                    reason = segment.rejection_reason(settings.stt)
                    decisions.append(reason or "passed_quality")
                    if not reason:
                        quality_segments.append(segment)
                fresh = (quality_segments if stabilize
                         else history.select(quality_segments, window_start))
                src_text = "".join(segment.text for segment in fresh).strip()
                status = "accepted"
                if stop_evt.is_set() or not pause_evt.accepts(generation):
                    status = "obsolete"
                elif stt_ms > 5000:
                    status = "slow_stt"
                elif not quality_segments:
                    status = "no_accepted_speech"
                elif not fresh:
                    status = "overlapping_duplicate"
                elif not stabilize and len(src_text) < audio_cfg.min_text_length:
                    status = "too_short"
                elif len(src_text) > 200:
                    status = "too_long"
                _diagnose(diagnostics_file, event="stt", status=status,
                          window_start_sample=window_start, window_end_sample=chunk.end_sample,
                          stt_ms=stt_ms, decisions=decisions, selected_text=src_text,
                          amplitude=amplitude,
                          speech_ratio=transcription.speech_seconds / (len(window) / sample_rate),
                          **transcription.diagnostics())
                if status == "slow_stt":
                    audio_chunks.clear()
                    drain_audio(audio_q)
                    context.clear()
                    history.clear()
                    assembler.clear()
                    caption_cache.clear()
                    prev_src = ""
                    last_audio_end = None
                    print(f"[WARN] STT took {stt_ms:.0f}ms, flushed stale audio buffer")
                if status not in ("accepted", "no_accepted_speech"):
                    continue
                if stabilize:
                    effective_src = transcription.language if src == "auto" else src
                    updates = assembler.observe(quality_segments, window_start,
                                                chunk.end_sample, effective_src)
                    _diagnose(diagnostics_file, event="caption_assembly",
                              pending=assembler.pending, update_count=len(updates),
                              window_start_sample=window_start, window_end_sample=chunk.end_sample)
                    publish(updates, chunk, window_start, stt_ms)
                    trim_sealed_audio()
                elif status == "accepted":
                    effective_src = transcription.language if src == "auto" else src
                    publish([CaptionUpdate(None, src_text, effective_src, True, 1, "legacy")],
                            chunk, window_start, stt_ms)
                    if not stop_evt.is_set() and pause_evt.accepts(generation):
                        history.commit(fresh, window_start)


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


def _pipeline_watchdog(settings, overlay, stop_evt: threading.Event, pause_evt: PauseState, tray_ref: list) -> None:
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
        if stop_evt.wait(3):
            break
        if tray_ref[0] and not pause_evt.is_set():
            tray_ref[0].icon = _create_tray_icon("active")
            tray_ref[0].title = "stream-caption"


def main():
    try:
        settings = load_settings()
    except SettingsError as exc:
        raise SystemExit(f"Settings error: {exc}") from exc
    overlay = SubtitleOverlay(settings.overlay)
    overlay.start()

    stop_evt = threading.Event()
    pause_evt = PauseState()
    tray_ref: list = [None]

    watchdog = threading.Thread(
        target=_pipeline_watchdog,
        args=(settings, overlay, stop_evt, pause_evt, tray_ref),
        daemon=True,
    )
    watchdog.start()

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
        pystray.MenuItem(
            "Auto-hide subtitles",
            lambda icon, item: overlay.toggle_auto_hide(),
            checked=lambda item: overlay.auto_hide_enabled,
        ),
        pystray.MenuItem("Quit", on_quit),
    )

    hotkey_str = settings.hotkey.toggle
    listener = None
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
    try:
        tray.run()
    finally:
        stop_evt.set()
        if listener is not None:
            listener.stop()
        # Let the pipeline join its reader and close the recorder before exit.
        watchdog.join()


if __name__ == "__main__":
    main()

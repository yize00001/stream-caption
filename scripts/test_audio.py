"""
Phase 2 validation: soundcard WASAPI Loopback + faster-whisper GPU + Claude Haiku translation
Usage: uv run python scripts/test_audio.py
"""

# ── 1. Standard library ────────────────────────────────────────────────────────
import os
import sys
import time

# ── 2. Third-party packages ────────────────────────────────────────────────────
import numpy as np

# Must be called before importing ctranslate2/faster_whisper on Windows,
# so Python can locate the CUDA .dll files (cublas64_12.dll etc.)
os.add_dll_directory(r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin")

import soundcard as sc
from faster_whisper import WhisperModel

# ── 3. Local modules ───────────────────────────────────────────────────────────
# Add src/ to the module search path so `import stream_caption.xxx` resolves
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from stream_caption.translator import translate

# ── 4. Constants ───────────────────────────────────────────────────────────────
SAMPLE_RATE = 16000       # Whisper requires 16 kHz audio
CHUNK_SECONDS = 3         # Audio chunk duration per transcription cycle
SILENCE_THRESHOLD = 0.01  # Skip transcription if mean absolute amplitude is below this


# ── 5. Functions ───────────────────────────────────────────────────────────────

def list_devices():
    print("=== Available speakers (loopback sources) ===")
    for i, speaker in enumerate(sc.all_speakers()):
        print(f"  [{i}] {speaker.name}")
    print()


def load_model() -> WhisperModel:
    print("Loading faster-whisper large-v3 (GPU)...")
    start = time.time()
    # device="cuda" uses GPU; compute_type="float16" enables half-precision for speed
    model = WhisperModel("large-v3", device="cuda", compute_type="float16")
    print(f"Model loaded in {time.time() - start:.1f}s\n")
    return model


def is_silent(audio: np.ndarray) -> bool:
    return float(np.abs(audio).mean()) < SILENCE_THRESHOLD


def transcribe(model: WhisperModel, audio: np.ndarray) -> tuple[str, str]:
    segments, info = model.transcribe(
        audio,
        language="ja",
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )
    # segments is a generator; join all chunks into a single string
    text = "".join(seg.text for seg in segments).strip()
    return text, info.language


# ── 6. Entry point ─────────────────────────────────────────────────────────────

def main():
    list_devices()

    default_speaker = sc.default_speaker()
    print(f"Using default speaker loopback: {default_speaker.name}\n")

    model = load_model()

    print(f"Capturing audio (transcribing every {CHUNK_SECONDS}s). Press Ctrl+C to stop.\n")
    print("-" * 60)

    with sc.get_microphone(default_speaker.id, include_loopback=True).recorder(
        samplerate=SAMPLE_RATE
    ) as mic:
        while True:
            # Record a fixed-length chunk (blocks until enough frames are captured)
            audio = mic.record(numframes=SAMPLE_RATE * CHUNK_SECONDS)

            # Downmix to mono — Whisper expects single-channel audio
            audio_mono = audio[:, 0] if audio.ndim > 1 else audio

            if is_silent(audio_mono):
                continue

            t0 = time.time()
            ja_text, _ = transcribe(model, audio_mono.astype(np.float32))
            stt_time = time.time() - t0

            if not ja_text:
                continue

            t1 = time.time()
            zh_text = translate(ja_text)
            translate_time = time.time() - t1

            print(f"[STT {stt_time:.2f}s] {ja_text}")
            print(f"[TL  {translate_time:.2f}s] {zh_text}")
            print()


# Only runs when this file is executed directly, not when imported
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")

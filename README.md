# stream-caption

Real-time speech recognition and translation overlay for YouTube/Twitch live streams, Japanese games, and video meetings.

**v1.3.8** | [繁體中文說明](README.zh-TW.md)

## Stack

- Audio: `soundcard` (WASAPI Loopback, dedicated recording thread)
- STT: `faster-whisper large-v3` (local GPU/CUDA, CPU fallback, auto language detection)
- Translation: DeepL API (primary) → SakuraLLM via Ollama (fallback, ja→zh only) → `opencc` s2twp
- UI: `tkinter` floating overlay (always-on-top, draggable, resizable, position memory)
- Tray: `pystray` — Pause/Resume/Quit, state icons (active/paused/error)
- Hotkey: `pynput` — `Ctrl+Shift+H` toggles overlay visibility
- Config: `.env` + `settings.toml`

## Translation backends

| | DeepL API | SakuraLLM (Ollama) |
|---|---|---|
| Language pairs | Any (ja, en, ko, zh, fr, de…) | Japanese → Chinese only |
| Setup | Free API key, cloud | Local model (~9 GB download) |
| Quality | High | High for ACGN content |
| Requires internet | Yes | No |
| Role | **Primary** | Fallback when DeepL unavailable |

**Recommended**: set up DeepL (free, 1M chars/month). SakuraLLM is optional — only useful if you need offline Japanese→Chinese translation.

## Requirements

- Python 3.11+, uv
- Windows 11 (WASAPI Loopback)
- **NVIDIA GPU with ≥4GB VRAM + CUDA 12.x — required for real-time use**
- DeepL API key (free) — or Ollama + SakuraLLM for offline ja→zh fallback

> ⚠️ **CPU mode is not suitable for live use.** Without a GPU, each segment takes 20–30 seconds to transcribe — too slow for real-time conversation. CPU mode exists as a fallback but is only practical for non-live audio (recordings, slow-paced content).

## Setup

### 1. Install Python and uv

1. Download and install [Python 3.11+](https://www.python.org/downloads/) — check **"Add Python to PATH"** during installation
2. Install uv (package manager):
```powershell
pip install uv
```

### 2. Install dependencies

> **Windows:** If you see a symlink error during `uv sync`, enable Developer Mode first:
> **Settings → System → For developers → Developer Mode → On**

```powershell
uv sync
copy .env.example .env
```

### 3. Get a DeepL API key (free, recommended)

1. Go to [deepl.com/en/pro-api](https://www.deepl.com/en/pro-api) and sign up for a free account
2. Under **Account** → **API Keys**, create a new key
3. The free plan includes 1M characters/month — no credit card required
4. Paste the key into `.env`:

```
DEEPL_API_KEY=your_key_here
```

### 4. (Optional) Set up SakuraLLM for offline ja→zh fallback

> Skip this if you have a DeepL API key. SakuraLLM is only needed as an offline fallback for Japanese → Chinese translation.

```powershell
winget install Ollama.Ollama

# Download GGUF from HuggingFace (~9GB):
# https://huggingface.co/SakuraLLM/Sakura-14B-Qwen2.5-v1.0-GGUF
# Recommended: sakura-14b-qwen2.5-v1.0-q4km.gguf

# Edit Modelfile: set correct GGUF path, then:
ollama create sakura -f Modelfile
```

## Usage

```powershell
# Double-click start.bat  (or)
uv run stream-caption
```

Right-click the tray icon to Pause/Resume or Quit.
Press `Ctrl+Shift+H` to toggle overlay visibility.

> **First run:** The Whisper model (~3GB) will be downloaded automatically on startup.
> The tray icon tooltip will show **"downloading model..."** during this time.
> Wait until the terminal shows `✓ Model ready` before expecting subtitles.
> A HuggingFace rate-limit warning may appear — this is harmless and can be ignored.

## Configuration (`settings.toml`)

```toml
[audio]
device = ""                  # audio device name (empty = system default)
silence_threshold = 0.003
window_seconds = 4
step_seconds = 2
min_text_length = 4

[stt]
model = "large-v3"           # large-v3 (best) / medium / small — see hardware guide below
beam_size = 5                # 1=fastest, 5=most accurate (default)
vocab = [                    # proper nouns for better STT recognition
    "にじさんじ", "ホロライブ",
    # add game/VTuber names here
]

[translation]
source_lang = "auto"         # "auto" or: ja en ko zh fr de
target_lang = "zh-TW"        # zh-TW zh-CN en ja ko fr de

[overlay]
width = 700
height = 160
opacity = 0.88
auto_hide_enabled = true    # false = keep the overlay visible
auto_hide_seconds = 8
font_family = "Microsoft JhengHei"
font_size_zh = 18
font_size_ja = 12
fg_zh = "#FFD700"
fg_ja = "#87CEEB"
bg_color = "#1a1a1a"

[log]
enabled = false              # set to true to save transcription logs to logs/

[hotkey]
toggle = "<ctrl>+<shift>+h"  # toggle overlay visibility
```

### Example configurations

**Japanese stream → Traditional Chinese (default)**
```toml
[translation]
source_lang = "auto"
target_lang = "zh-TW"
```

**English meeting → Traditional Chinese**
```toml
[translation]
source_lang = "en"
target_lang = "zh-TW"
```

**Japanese meeting → English**
```toml
[translation]
source_lang = "ja"
target_lang = "en"
```

## Utterance buffering and caption revisions

`[stt] stabilize_captions = true` is the default. Pending audio is retained across recognition passes. After two observations, continuous speech can show a draft; subsequent results revise the same caption instead of adding history entries. This delays commitment and permits correction; two observations do not guarantee identical or correct recognition.

After the configured observation count, captions finalize on an estimated 0.8-second pause, or at the buffer limit. A subsequent no-speech window can also seal pending speech. The default cap is 8 seconds; the effective cap is the larger of `audio.window_seconds` and `caption_buffer_seconds`, rounded up to a chunk boundary. Only finalized successful translations enter context.

Drafts are marked `[暫定]` (provisional); corrections can include sentence-final negation. Japanese, Chinese and Korean retain complete segments and suppress only identical overlapping sealed segments, since alignment entries can be subword pieces. This may retain some repeated context. Word timings remain in diagnostics, and other languages can use whole word entries for overlap removal. Long sentences can still split at the cap, and recognition itself can return fragments.

Continuous speech typically waits one extra chunk before the first draft (about 2 seconds by default). Longer audio and word alignment add STT work; revised drafts can increase translated character usage. An unchanged final caption reuses its translation. Settings under `[stt]` are `stabilize_captions`, `caption_buffer_seconds = 8`, `caption_silence_seconds = 0.8` and `caption_stability_passes = 2`. Disable stabilization to use the previous rolling-window mode. Pause transitions and audio gaps clear pending state. Short drafts wait; final captions may retain two-character replies, while single-character replies require the configured observation count.

Use `[stt] vocab` for recognition hints and `[translation] topic_context` for optional topic background. For a Japanese drinking-chat clip, examples are `vocab = ["ちゃんぽん", "飲酒部", "ぶいすぽっ！"]` and `topic_context = "日本語の雑談配信。飲み会とお酒についての会話。"`. Topic context is empty by default and sent to the active translation backend; change it with the content. It does not rewrite source words or guarantee homophone correction.

Translation diagnostics include `caption_id`, `revision`, `final`, `caption_reason` and `cache_reused`. Multiple records sharing an ID are revisions, not independent sentences.

```powershell
uv run python scripts/replay_captions.py logs/<name>.diagnostics.jsonl --output logs/caption-replay.json
```

Replay does not call translation APIs. Old fixed-window logs cannot reproduce longer-buffer recognition or live word alignment; replay validates state transitions, not accuracy or latency.

## Recognition and translation quality

- `zh-TW` requests native Traditional Chinese (`ZH-HANT`) from DeepL, retaining the existing OpenCC Taiwan wording conversion.
- In legacy mode, deduplication suppresses identical text covering overlapping audio; reworded or differently segmented overlaps may still repeat. The default stabilization mode revises pending text under one caption ID.
- Whisper defaults to no previous-caption prompt (`[stt] use_previous_text = false`). Final quality filtering combines low log probability with high no-speech probability or repetition, rather than banning greeting phrases. Configure `quality_filter`, `min_avg_logprob`, `max_no_speech_prob` and `max_compression_ratio` under `[stt]`. Scores are not accuracy percentages; tune with real audio.
- Translation context keeps up to 3 complete pairs, 1000 combined characters and 15 seconds of same-language history. Language changes, pause transitions and audio gaps reset it. See `[translation] context_max_sentences`, `context_max_characters` and `context_max_age_seconds`.
- `[translation] model_type` accepts `default` (omit the API option), `latency_optimized`, `quality_optimized` or `prefer_quality_optimized`. Availability depends on the language pair and account; compare quality and latency before changing it.
- `[translation] glossary_id` accepts an existing DeepL glossary ID matching the language pair; empty disables it. The app does not create glossaries. STT `vocab` hints and translation glossaries serve different purposes.
- Failed translation preserves the original caption with an unavailable message. Sakura fallback retains all translated lines and reports token-limit truncation as incomplete.

For diagnosis, add `diagnostics_enabled = true` to the existing `[log]` section and restart. `logs/*.diagnostics.jsonl` contains source/translated text, segment times, quality signals, filtering decisions, backend and timings, without audio or API keys. This is disabled by default and independent of `log.enabled`.

`latest_chunk_age_ms` measures time since the latest chunk finished recording, not full speech-to-subtitle latency. Sample offsets align overlapping windows and detect missing chunks. Background translation and request timeout tuning remain separate work.

## Subtitle auto-hide switch

Right-click the tray icon and check or uncheck **Auto-hide subtitles** to change auto-hide for the current session. With auto-hide off, the window stays visible; `Ctrl+Shift+H` still manually hides or shows it.

To disable it on every launch, add `auto_hide_enabled = false` under `[overlay]` in `settings.toml`. Existing configurations keep the default (enabled, 8 seconds). Tray changes do not rewrite the file. Turning it off also shows an empty overlay before the first subtitle; turning it back on starts a fresh countdown.

## Audio timing and pause behavior

- `audio.step_seconds` controls the actual recording chunk length. `window_seconds` controls the rolling STT window.
- Both must be positive integer seconds, and the window must be a multiple of the step: for example, `4 / 2` (default) or `2 / 1`.
- Invalid values and unknown setting names produce a startup error before background workers start.
- Paused capture is read and discarded. Resume clears the old window and translation context, then waits for a fresh full window. Audio spanning a pause transition and in-flight results from before that transition are discarded.
- Capture opens after the model is ready. On exit or failure, the recording thread is stopped and joined before the device closes and the pipeline can restart.

Shorter windows may affect sentence completeness and accuracy; compare with the same audio. STT and translation still run sequentially; this is not streaming subtitle output.

### Development checks

```powershell
uv run python -m unittest discover -s tests -v
```

Tests use simulated audio, models and translation. They do not capture system audio, download models or call translation APIs. Real WASAPI, GPU, translation service and latency checks are separate.

## Hardware guide

| Hardware | Recommended model | STT speed |
|---|---|---|
| NVIDIA RTX 3000/4000/5000 (≥4GB VRAM) | `large-v3` | ~0.5s/segment |
| NVIDIA MX series / GTX (2–3GB VRAM) | `medium` | ~1–2s/segment |
| No GPU / integrated graphics | `medium` or `small` | ~10–30s/segment |

Set the model in `settings.toml`:
```toml
[stt]
model = "medium"   # change from large-v3 if your PC is slow or has limited VRAM
```

## Notes

- Windows only (WASAPI Loopback)
- **NVIDIA GPU (RTX 3000/4000 series):** Install [CUDA Toolkit 12.8](https://developer.nvidia.com/cuda-12-8-0-download-archive) — no extra steps needed
- **NVIDIA GPU (RTX 5000 series / Blackwell):** After installing CUDA Toolkit, also copy `cublas64_12.dll`, `cublasLt64_12.dll`, `cudart64_12.dll` from `CUDA\v12.8\bin` to `.venv\Lib\site-packages\ctranslate2\`
- **Low-end PC / no GPU?** Set `model = "medium"` or `model = "small"` in `[stt]` — the app falls back to CPU automatically
- After editing `Modelfile`, re-run `ollama create sakura -f Modelfile`
- `settings.toml` and `window-state.json` are gitignored (personal config)

## Credits

- [SakuraLLM](https://github.com/SakuraLLM/Sakura-13B-Galgame) — ACGN-specialized Japanese→Chinese translation model, licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — Speech recognition
- [DeepL](https://www.deepl.com) — Neural machine translation
- [Ollama](https://ollama.com) — Local LLM runtime

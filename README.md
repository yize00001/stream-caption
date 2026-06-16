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

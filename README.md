# stream-caption

Real-time Japanese speech recognition and Traditional Chinese translation overlay for YouTube/Twitch live streams and Japanese games.

**v1.0.0**

## Stack

- Audio: `soundcard` (WASAPI Loopback, dedicated recording thread)
- STT: `faster-whisper large-v3` (local GPU/CUDA, CPU fallback)
- Translation: DeepL API (primary) → SakuraLLM via Ollama (fallback) → `opencc` s2twp
- UI: `tkinter` floating overlay (always-on-top, draggable, resizable, position memory)
- Tray: `pystray` — Pause/Resume/Quit, state icons (active/paused/error)
- Config: `.env` + `settings.toml`

## Requirements

- Python 3.11+, uv
- Windows 11 (WASAPI Loopback)
- NVIDIA GPU with CUDA 12.x (optional; falls back to CPU int8)
- DeepL API key (free, 1M chars lifetime) — or Ollama + SakuraLLM as fallback

## Setup

### 1. Install dependencies

```powershell
uv sync
copy .env.example .env
```

### 2. Configure `.env`

```
# DeepL (primary translation — get free key at deepl.com/en/pro-api)
DEEPL_API_KEY=your_key_here

# Ollama fallback (optional)
OLLAMA_BASE_URL=http://localhost:11434/v1
SAKURA_MODEL=sakura
```

### 3. (Optional) Set up SakuraLLM fallback

```powershell
winget install Ollama.Ollama

# Download GGUF from HuggingFace (~9GB):
# https://huggingface.co/SakuraLLM/Sakura-14B-Qwen2.5-v1.0-GGUF
# Recommended: sakura-14b-qwen2.5-v1.0-q4km.gguf

# Edit Modelfile: set correct GGUF path, then:
ollama create sakura -f Modelfile
```

### 4. (Optional) Audio isolation with VB-Cable

To prevent Discord/other apps from being transcribed:

1. Install [VB-Cable](https://vb-audio.com/Cable/) (free)
2. Windows Settings → Sound → App volume → set browser output to `CABLE Input`
3. Control Panel → Sound → Recording → `CABLE Output` → Listen → enable monitoring to your headphones
4. Set `settings.toml`:

```toml
[audio]
device = "CABLE Input"
```

## Usage

```powershell
# Double-click start.bat  (or)
uv run stream-caption
```

Right-click the tray icon to Pause/Resume or Quit.

## Configuration (`settings.toml`)

```toml
[audio]
device = "CABLE Input"       # audio device name (empty = system default)
silence_threshold = 0.003
window_seconds = 4
step_seconds = 2
min_text_length = 4

[stt]
vocab = [                    # proper nouns for better STT recognition
    "にじさんじ", "ホロライブ",
    # add game/VTuber names here
]

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
```

## Notes

- Windows only (WASAPI Loopback)
- CUDA DLL workaround: copy `cublas64_12.dll`, `cublasLt64_12.dll`, `cudart64_12.dll` from `CUDA\v12.x\bin` to `.venv\Lib\site-packages\ctranslate2\`
- After editing `Modelfile`, re-run `ollama create sakura -f Modelfile`
- `settings.toml` and `window-state.json` are gitignored (personal config)

## Credits

- [SakuraLLM](https://github.com/SakuraLLM/Sakura-13B-Galgame) — ACGN-specialized Japanese→Chinese translation model, licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — Speech recognition
- [DeepL](https://www.deepl.com) — Neural machine translation
- [Ollama](https://ollama.com) — Local LLM runtime

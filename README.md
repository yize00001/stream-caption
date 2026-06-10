# stream-caption

Real-time Japanese speech recognition and Traditional Chinese translation overlay for YouTube/Twitch live streams.

## Stack

- Audio: `soundcard` (WASAPI Loopback)
- STT: `faster-whisper large-v3` (local GPU, CUDA auto-detected, CPU fallback)
- Translation: SakuraLLM via Ollama (local, free) or Claude Haiku API (fallback)
- Post-processing: `opencc` Simplified → Traditional Chinese
- UI: `tkinter` floating overlay (always-on-top, draggable, 2 pairs JA+ZH)
- Config: `.env`

## Requirements

- Python 3.11+, uv
- NVIDIA GPU with CUDA 12.x (optional; falls back to CPU)
- [Ollama](https://ollama.com) + SakuraLLM model (for local translation)
- Anthropic API key (optional, for Claude fallback)

## Setup

### 1. Install dependencies

```powershell
uv sync
copy .env.example .env
```

### 2. Set up SakuraLLM (local translation)

```powershell
# Install Ollama
winget install Ollama.Ollama

# Download GGUF from HuggingFace:
# https://huggingface.co/SakuraLLM/Sakura-14B-Qwen2.5-v1.0-GGUF
# Recommended: sakura-14b-qwen2.5-v1.0-q4km.gguf (~9GB)

# Edit Modelfile: set the correct GGUF path, then:
ollama create sakura -f Modelfile
```

### 3. Configure `.env`

```
TRANSLATOR_BACKEND=sakura        # or "claude" to use Anthropic API
ANTHROPIC_API_KEY=your_key_here  # only needed if TRANSLATOR_BACKEND=claude
OLLAMA_BASE_URL=http://localhost:11434/v1
SAKURA_MODEL=sakura
```

## Usage

```powershell
# Main app
uv run stream-caption

# STT-only test (no overlay)
uv run python scripts/test_audio.py
```

## Notes

- Windows only (WASAPI Loopback)
- CUDA DLL workaround: copy `cublas64_12.dll`, `cublasLt64_12.dll`, `cudart64_12.dll` from `CUDA\v12.x\bin` to `.venv\Lib\site-packages\ctranslate2\`
- Double-click the overlay window to close

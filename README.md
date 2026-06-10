# stream-caption

Real-time Japanese speech recognition and Traditional Chinese translation overlay for live streams.

## Stack

- Audio: `soundcard` (WASAPI Loopback)
- STT: `faster-whisper large-v3` (local GPU)
- Translation: Claude API (`claude-haiku-4-5`)
- UI: `tkinter` floating window
- Config: `.env`

## Requirements

- Python 3.11+, uv
- NVIDIA GPU with CUDA 12.x (auto-detected; falls back to CPU)
- Anthropic API key

## Setup

```powershell
uv sync
copy .env.example .env
# fill in ANTHROPIC_API_KEY in .env
```

## Usage

```powershell
# Phase 1 test (STT only)
uv run python scripts/test_audio.py

# Main app (Phase 3+)
uv run python -m stream_caption
```

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

_SETTINGS_PATH = Path(__file__).parent.parent.parent / "settings.toml"


@dataclass
class OverlaySettings:
    font_family: str = "Microsoft JhengHei"
    font_size_zh: int = 18
    font_size_ja: int = 12
    bg_color: str = "#1a1a1a"
    fg_zh: str = "#FFD700"
    fg_ja: str = "#87CEEB"
    opacity: float = 0.88
    width: int = 700
    height: int = 160
    auto_hide_seconds: int = 8


@dataclass
class AudioSettings:
    silence_threshold: float = 0.003
    window_seconds: int = 4
    step_seconds: int = 2
    min_text_length: int = 4
    device: str = ""  # empty = system default speaker


@dataclass
class STTSettings:
    vocab: list[str] = field(default_factory=list)  # proper nouns for initial_prompt


@dataclass
class HotkeySettings:
    toggle: str = "<ctrl>+<shift>+h"  # toggle overlay visibility


@dataclass
class Settings:
    overlay: OverlaySettings = field(default_factory=OverlaySettings)
    audio: AudioSettings = field(default_factory=AudioSettings)
    stt: STTSettings = field(default_factory=STTSettings)
    hotkey: HotkeySettings = field(default_factory=HotkeySettings)


def load_settings() -> Settings:
    s = Settings()
    if not _SETTINGS_PATH.exists():
        return s
    with open(_SETTINGS_PATH, "rb") as f:
        data = tomllib.load(f)
    for section, obj in (("overlay", s.overlay), ("audio", s.audio), ("stt", s.stt), ("hotkey", s.hotkey)):
        for k, v in data.get(section, {}).items():
            if hasattr(obj, k):
                setattr(obj, k, v)
    return s

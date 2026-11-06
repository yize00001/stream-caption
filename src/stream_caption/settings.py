import math
import re
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
    auto_hide_enabled: bool = True
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
    model: str = "auto"  # auto / large-v3 / medium / small (auto detects best model for your GPU)
    vocab: list[str] = field(default_factory=list)  # proper nouns for initial_prompt
    beam_size: int = 5  # 1=fastest, 5=most accurate
    use_previous_text: bool = False
    quality_filter: bool = True
    min_avg_logprob: float = -1.0
    max_no_speech_prob: float = 0.6
    max_compression_ratio: float = 2.4
    stabilize_captions: bool = True
    caption_buffer_seconds: int = 8
    caption_silence_seconds: float = 0.8
    caption_stability_passes: int = 2


@dataclass
class LogSettings:
    enabled: bool = False  # set to true to enable log files in logs/
    diagnostics_enabled: bool = False  # opt-in JSONL containing source and translated text


@dataclass
class TranslationSettings:
    source_lang: str = "auto"   # "auto" or ISO 639-1: ja en ko zh fr de
    target_lang: str = "zh-TW"  # zh-TW zh-CN en ja ko fr de
    context_max_sentences: int = 3
    context_max_characters: int = 1000
    context_max_age_seconds: int = 15
    model_type: str = "default"
    glossary_id: str = ""
    topic_context: str = ""


@dataclass
class HotkeySettings:
    toggle: str = "<ctrl>+<shift>+h"  # toggle overlay visibility


@dataclass
class Settings:
    overlay: OverlaySettings = field(default_factory=OverlaySettings)
    audio: AudioSettings = field(default_factory=AudioSettings)
    stt: STTSettings = field(default_factory=STTSettings)
    translation: TranslationSettings = field(default_factory=TranslationSettings)
    log: LogSettings = field(default_factory=LogSettings)
    hotkey: HotkeySettings = field(default_factory=HotkeySettings)


class SettingsError(ValueError):
    """A configuration error that should be fixed before starting workers."""


def validate_settings(s: Settings) -> None:
    for section in ("overlay", "audio", "stt", "translation", "log", "hotkey"):
        obj = getattr(s, section)
        defaults = type(obj)()
        for name, value in vars(obj).items():
            default = getattr(defaults, name)
            key = f"{section}.{name}"
            if isinstance(default, float):
                valid = type(value) in (int, float) and math.isfinite(value)
            elif isinstance(default, list):
                valid = isinstance(value, list) and all(isinstance(v, str) for v in value)
            else:
                valid = type(value) is type(default)
            if not valid:
                raise SettingsError(f"{key}: expected {type(default).__name__}")
            if isinstance(default, str) and name not in ("device", "glossary_id", "topic_context") and not value.strip():
                raise SettingsError(f"{key}: must not be empty")

    for section, names in (
        ("audio", ("window_seconds", "step_seconds", "min_text_length")),
        ("overlay", ("width", "height", "font_size_zh", "font_size_ja", "auto_hide_seconds")),
        ("stt", ("beam_size", "caption_buffer_seconds", "caption_stability_passes", "caption_silence_seconds")),
        ("translation", ("context_max_sentences", "context_max_characters", "context_max_age_seconds")),
    ):
        for name in names:
            if getattr(getattr(s, section), name) <= 0:
                raise SettingsError(f"{section}.{name}: must be greater than zero")
    if s.audio.window_seconds % s.audio.step_seconds != 0:
        raise SettingsError("audio.window_seconds: must be an integer multiple of audio.step_seconds")
    for key, value in (("audio.silence_threshold", s.audio.silence_threshold),
                       ("stt.max_no_speech_prob", s.stt.max_no_speech_prob),
                       ("overlay.opacity", s.overlay.opacity)):
        if not 0 <= value <= 1:
            raise SettingsError(f"{key}: must be between 0 and 1")
    if s.stt.min_avg_logprob > 0:
        raise SettingsError("stt.min_avg_logprob: must be zero or negative")
    if s.stt.max_compression_ratio <= 0:
        raise SettingsError("stt.max_compression_ratio: must be greater than zero")
    if s.translation.model_type not in (
        "default", "latency_optimized", "quality_optimized", "prefer_quality_optimized"
    ):
        raise SettingsError("translation.model_type: unsupported model type")
    for name in ("bg_color", "fg_zh", "fg_ja"):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", getattr(s.overlay, name)):
            raise SettingsError(f"overlay.{name}: expected a color such as #FFD700")


def load_settings(path: Path | None = None) -> Settings:
    path = _SETTINGS_PATH if path is None else path
    s = Settings()
    if not path.exists():
        return s
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SettingsError(f"Cannot read {path}: {exc}") from exc
    sections = {"overlay", "audio", "stt", "translation", "log", "hotkey"}
    if data.keys() - sections:
        raise SettingsError(f"Unknown settings section: {sorted(data.keys() - sections)[0]}")
    for section, obj in (
        ("overlay", s.overlay),
        ("audio", s.audio),
        ("stt", s.stt),
        ("translation", s.translation),
        ("log", s.log),
        ("hotkey", s.hotkey),
    ):
        values = data.get(section, {})
        if not isinstance(values, dict):
            raise SettingsError(f"{section}: expected a TOML table")
        for k, v in values.items():
            if k not in vars(obj):
                raise SettingsError(f"Unknown setting: {section}.{k}")
            setattr(obj, k, v)
    validate_settings(s)
    return s

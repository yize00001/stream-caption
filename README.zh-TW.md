# stream-caption

即時語音辨識與翻譯字幕浮動視窗，適用於 YouTube / Twitch 日文直播、日文遊戲、或與外國客戶的視訊會議。

**v1.3.8** | [English](README.md)

## 翻譯後端說明

| | DeepL API | SakuraLLM（Ollama） |
|---|---|---|
| 支援語言對 | 任意（日、英、韓、中、法、德…） | 僅日文 → 中文 |
| 設定方式 | 免費申請 API key，雲端翻譯 | 本地模型（需下載約 9GB） |
| 翻譯品質 | 高 | 高（ACGN 內容專用） |
| 需要網路 | 是 | 否 |
| 角色 | **主要翻譯** | DeepL 無法使用時的備援 |

**建議**：申請 DeepL 免費 API key（每月 100 萬字，不需信用卡）。SakuraLLM 為選配，僅在需要離線日文→中文翻譯時才需要設定。

## 系統需求

- Python 3.11+、uv
- Windows 11（WASAPI Loopback）
- **NVIDIA GPU ≥4GB VRAM + CUDA 12.x — 即時使用必須**
- DeepL 免費 API key — 或使用 Ollama + SakuraLLM 做離線備援（僅日文→中文）

> ⚠️ **沒有 GPU 無法即時使用。** CPU 模式每段語音需要 20–30 秒才能辨識，對話早已繼續，完全來不及。CPU 模式僅適合非即時用途（錄音回放、慢速內容）。

## 安裝步驟

### 1. 安裝 Python 與 uv

1. 下載並安裝 [Python 3.11+](https://www.python.org/downloads/)，安裝時勾選 **「Add Python to PATH」**
2. 安裝 uv（套件管理工具）：
```powershell
pip install uv
```

### 2. 安裝依賴套件

> **Windows 注意：** 若 `uv sync` 出現符號連結錯誤，請先開啟開發人員模式：
> **設定 → 系統 → 開發人員專用 → 開發人員模式 → 開啟**

```powershell
uv sync
copy .env.example .env
```

### 3. 申請 DeepL API key（免費，建議設定）

1. 前往 [deepl.com/en/pro-api](https://www.deepl.com/en/pro-api) 註冊免費帳號
2. 登入後進入 **Account** → **API Keys**，點選 **Create API key**
3. 免費方案每月 100 萬字，不需信用卡
4. 將 key 填入 `.env`：

```
DEEPL_API_KEY=your_key_here
```

### 4. （選配）設定 SakuraLLM 離線日文→中文備援

> 如果已有 DeepL API key 可跳過此步驟。SakuraLLM 僅在 DeepL 無法使用時作為備援。

```powershell
# 安裝 Ollama
winget install Ollama.Ollama

# 從 HuggingFace 下載 GGUF（約 9GB）：
# https://huggingface.co/SakuraLLM/Sakura-14B-Qwen2.5-v1.0-GGUF
# 建議下載：sakura-14b-qwen2.5-v1.0-q4km.gguf

# 編輯 Modelfile，設定 GGUF 路徑後建立模型：
ollama create sakura -f Modelfile
```

## 啟動

```powershell
# 雙擊 start.bat（或）
uv run stream-caption
```

- 右鍵點選系統匣圖示可 **暫停 / 繼續 / 結束**
- 按 `Ctrl+Shift+H` 切換字幕視窗顯示/隱藏

> **首次啟動：** Whisper 模型（~3GB）會在啟動時自動下載。
> 下載期間系統匣圖示 tooltip 會顯示 **「downloading model...」**。
> 請等到終端機出現 `✓ Model ready` 才表示準備完成。
> 過程中出現 HuggingFace 的速率限制警告屬正常現象，可忽略。

## 設定檔（`settings.toml`）

複製 `settings.toml.example` 為 `settings.toml` 後編輯：

```toml
[audio]
device = ""                  # 音訊裝置名稱（空字串 = 系統預設）
silence_threshold = 0.003
window_seconds = 4
step_seconds = 2
min_text_length = 4

[stt]
model = "large-v3"           # large-v3（最準）/ medium / small — 低階電腦請參考下方硬體說明
beam_size = 5                # 辨識精度 vs 速度：1=最快，5=最準確（預設）
vocab = [                    # 幫助 Whisper 辨識的專有名詞
    "にじさんじ", "ホロライブ",
    # 可加入遊戲名、角色名等
]

[translation]
source_lang = "auto"         # "auto" 或指定：ja en ko zh fr de
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
enabled = false              # 設為 true 可將辨識紀錄存到 logs/ 資料夾

[hotkey]
toggle = "<ctrl>+<shift>+h"  # 切換字幕顯示/隱藏
```

### 常用情境設定

**日文直播 / 遊戲 → 繁體中文（預設）**
```toml
[translation]
source_lang = "auto"
target_lang = "zh-TW"
```

**英文客戶會議 → 繁體中文**
```toml
[translation]
source_lang = "en"
target_lang = "zh-TW"

[audio]
device = ""   # 系統預設麥克風
```

**日文客戶會議 → 英文**
```toml
[translation]
source_lang = "ja"
target_lang = "en"
```

## 硬體建議

| 硬體 | 建議 model | STT 速度 |
|---|---|---|
| NVIDIA RTX 3000/4000/5000（≥4GB VRAM） | `large-v3` | ~0.5 秒/段 |
| NVIDIA MX 系列 / GTX（2–3GB VRAM） | `medium` | ~1–2 秒/段 |
| 無獨顯 / 整合顯示卡 | `medium` 或 `small` | ~10–30 秒/段 |

在 `settings.toml` 設定：
```toml
[stt]
model = "medium"   # 低階電腦或 VRAM 不足時，從 large-v3 改成 medium
```

## 注意事項

- 僅支援 Windows（WASAPI Loopback）
- **NVIDIA GPU（RTX 3000 / 4000 系列）：** 安裝 [CUDA Toolkit 12.8](https://developer.nvidia.com/cuda-12-8-0-download-archive) 即可，不需要其他步驟
- **NVIDIA GPU（RTX 5000 系列 / Blackwell 架構）：** 安裝 CUDA Toolkit 後，還需將 `cublas64_12.dll`、`cublasLt64_12.dll`、`cudart64_12.dll` 從 `CUDA\v12.8\bin` 複製到 `.venv\Lib\site-packages\ctranslate2\`
- **低階電腦 / 無獨顯？** 在 `[stt]` 設定 `model = "medium"` 或 `model = "small"`，程式會自動以 CPU 模式執行
- 修改 `Modelfile` 後需重新執行 `ollama create sakura -f Modelfile`
- `settings.toml` 和 `window-state.json` 已加入 `.gitignore`（個人設定，不進版本控管）

## 版權聲明

- [SakuraLLM](https://github.com/SakuraLLM/Sakura-13B-Galgame) — ACGN 專用日文→中文翻譯模型，授權：[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — 語音辨識
- [DeepL](https://www.deepl.com) — 神經機器翻譯
- [Ollama](https://ollama.com) — 本地 LLM 執行環境

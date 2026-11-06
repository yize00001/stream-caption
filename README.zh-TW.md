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
auto_hide_enabled = true    # false = 關閉自動隱藏
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
device = ""   # 系統預設喇叭 loopback，擷取會議對方的聲音；不是麥克風輸入
```

**日文客戶會議 → 英文**
```toml
[translation]
source_lang = "ja"
target_lang = "en"
```

## 句子累積與字幕修正

預設開啟 `[stt] stabilize_captions = true`。持續說話時，程式保留尚未定稿的音訊，預設經過兩次觀察後顯示暫定字幕；後續辨識修正同一筆原文與譯文，不會每次都追加到歷史。這是延後提交與持續修訂，並不保證兩次辨識文字完全相同或最終辨識正確。

達設定觀察次數後偵測到約 0.8 秒停頓，或達到音訊緩衝上限時定稿；下一個無語音視窗也可完成待定字幕。後一句只使用已定稿且翻譯成功的上下文。預設上限為 8 秒，實際取 `audio.window_seconds` 與 `caption_buffer_seconds` 較大者，再向上對齊切片長度。

暫定字幕會標示 `[暫定]`，內容仍可能修正，包括補上句尾否定。日文、中文與韓文保留完整辨識片段，只抑制文字相同且時間重疊的已定稿片段，避免把逐字時間中的詞片段裁成半個詞；因此有時仍會保留部分重疊內容。逐字時間仍保留作診斷；其他語言可用完整 word 項目處理交疊。緩衝達上限仍可能切開長句，模型本身也可能回傳破碎片段。

持續說話時，第一筆字幕通常會多等一次切片（預設約 2 秒）；逐字時間與較長音訊也增加辨識工作量。修訂可能重新翻譯，使 API 字數用量增加；文字未變的定稿會沿用上一版譯文。可在既有 `[stt]` 區塊調整：

```toml
stabilize_captions = true
caption_buffer_seconds = 8
caption_silence_seconds = 0.8
caption_stability_passes = 2
```

設為 `stabilize_captions = false` 可回到前一輪的固定滾動視窗與保守去重模式。暫停恢復或音訊缺口會捨棄未完成的累積狀態。短於 `min_text_length` 的暫定字幕先不顯示；定稿時可保留至少兩字的短句，單字則需經過設定的觀察次數。

領域提示可搭配既有 `[stt] vocab` 與新增 `[translation] topic_context`。例如在對應區塊內合併下列設定：

```toml
[stt]
vocab = ["ちゃんぽん", "飲酒部", "ぶいすぽっ！"]

[translation]
topic_context = "日本語の雑談配信。飲み会とお酒についての会話。"
```

話題背景預設空白，使用者需依影片切換；它會送給目前使用的翻譯服務作為背景，沒有對原文做固定詞彙替換，也不能保證修正同音誤辨。

診斷的翻譯事件新增 `caption_id`、`revision`、`final`、`caption_reason` 與 `cache_reused`，可分辨修訂、定稿及譯文重用；同一 ID 多筆紀錄不代表多個獨立句子。

可離線重播既有診斷，完全不呼叫翻譯 API：

```powershell
uv run python scripts/replay_captions.py logs/<name>.diagnostics.jsonl --output logs/caption-replay.json
```

舊 LOG 的固定視窗與片段時間無法重現新模式的較長音訊或逐字對齊；重播只驗證流程，不是準確率或延遲測試。

## 辨識與翻譯品質

- `zh-TW` 直接要求 DeepL 使用繁體中文目標 `ZH-HANT`，仍保留既有 OpenCC 台灣用字後處理。
- 關閉句子累積模式時，去重只抑制相同文字且來自重疊音訊的片段；不同措辭或切句的重疊結果可能仍重複。預設模式改以同一字幕 ID 修訂待定內容。
- Whisper 預設不帶入前一句提示（`[stt] use_previous_text = false`）。辨識品質過濾採低 log probability 搭配高無語音機率或高重複度的聯合判斷，不封鎖「你好」「晚安」等正常句子。
- 過濾規則可由 `[stt] quality_filter`、`min_avg_logprob`、`max_no_speech_prob`、`max_compression_ratio` 調整；分數不代表準確率，仍需以真實音訊比較漏句與憑空字幕。
- 翻譯保留最多 3 句、合計 1000 字元、15 秒內的同語言上下文；語言切換、暫停恢復或音訊缺口會重設。可在 `[translation]` 調整 `context_max_sentences`、`context_max_characters`、`context_max_age_seconds`。
- `[translation] model_type` 可設 `default`（不指定，交由 DeepL 選擇）、`latency_optimized`、`quality_optimized` 或 `prefer_quality_optimized`；支援情況依語言對與帳戶而定。品質模式可能增加延遲，需實際比較。
- `[translation] glossary_id` 可填入既有且符合語言對的 DeepL 術語表 ID；空字串代表停用。本程式不會自動建立術語表。`[stt] vocab` 是辨識提示，與翻譯術語表不同。
- 翻譯失敗時保留原文並顯示「翻譯暫時不可用」。Sakura 備援保留多行完整譯文；遇到輸出長度截斷會視為未完成，不顯示為完整譯文。

要診斷誤辨識，在既有 `settings.toml` 的 `[log]` 加入 `diagnostics_enabled = true`，重新啟動後記錄到 `logs/*.diagnostics.jsonl`。紀錄包含原文、譯文、片段時間、辨識分數、過濾原因、實際翻譯服務及耗時，不包含音訊或 API 金鑰；預設關閉，可獨立於 `log.enabled` 使用。

診斷中的 `latest_chunk_age_ms` 是最新音訊切片讀取完成後到結果完成的時間，並非從說話開始計算的完整字幕延遲。音訊樣本位置可用來對齊重疊視窗與缺口；尚未加入背景翻譯或請求逾時調校。

## 字幕自動隱藏開關

右鍵系統匣圖示，勾選或取消 **Auto-hide subtitles**，可立即切換本次執行的自動隱藏。關閉時視窗保持顯示，`Ctrl+Shift+H` 仍可手動隱藏／顯示。

若希望每次啟動都關閉自動隱藏，在 `settings.toml` 的 `[overlay]` 加入 `auto_hide_enabled = false`。未設定時維持原本預設（開啟、8 秒）；系統匣切換不會改寫設定檔。關閉後即使沒有字幕，視窗也會顯示；重新開啟時，會從當下重新計時。

## 音訊設定與暫停行為

- `audio.step_seconds` 控制每次實際錄音長度；`window_seconds` 是送去辨識的滾動視窗長度。
- 兩者都必須是正整數秒，且 `window_seconds` 必須是 `step_seconds` 的整數倍。例如 `4 / 2`（預設）或 `2 / 1`。
- 無效設定或拼錯的設定名稱會在啟動前顯示錯誤，避免背景流程不斷重啟。
- 暫停時持續讀取裝置，但丟棄錄音；恢復時清除舊視窗及翻譯上下文，等新的完整視窗再辨識。跨越暫停／恢復的錄音及尚在處理的舊結果會被丟棄。
- 模型準備完成後才開始收音。流程結束或發生錯誤時，會先停止並等待錄音執行緒退出，再關閉裝置及重啟。

縮短視窗可能影響句子完整度與準確率，需使用相同音訊比較；目前仍是先辨識再翻譯，尚未改成串流字幕。

### 開發驗證

```powershell
uv run python -m unittest discover -s tests -v
```

測試使用模擬音訊、模型與翻譯，不會錄製系統聲音、下載模型或呼叫翻譯 API。實際 WASAPI、GPU、翻譯服務與延遲仍需另外測試。

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

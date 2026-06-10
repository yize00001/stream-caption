# stream-caption（暫名：live-translate-tool）

## 專案目的

觀看 YouTube / Twitch 日文直播時，即時將主播語音辨識並翻譯成繁體中文字幕，以浮動視窗顯示在螢幕上。

## 技術方向

- 語言：Python（uv + Python 3.14）
- 音訊擷取：`soundcard`（擷取 Windows 系統輸出音訊，不需動直播來源）
- 語音辨識：`faster-whisper`（本機 GPU，`large-v3` 模型，日文準確率高）
- 翻譯：Claude API（`claude-haiku-4-5`，語境翻譯，直播用語適應性佳）
- 字幕顯示：`tkinter` 浮動透明置頂視窗
- 設定：`.env` 管理 API key
- 版本管理：Git + GitHub

## 硬體條件

開發與執行環境：**家用桌機**

| 項目 | 規格 |
|---|---|
| CPU | AMD Ryzen 5 5600X |
| GPU | NVIDIA GeForce RTX 5060 Ti（16GB VRAM） |
| RAM | 32GB DDR4 |
| OS | Windows 11 |

RTX 5060 Ti 可流暢執行 `faster-whisper large-v3`，推論延遲約 0.5～1 秒。

## 架構流程

```
[YouTube / Twitch 瀏覽器]
        ↓ 系統音訊輸出（WASAPI Loopback）
[soundcard：滾動緩衝 2～3 秒音訊片段]
        ↓
[faster-whisper large-v3：日文 STT + VAD 斷句]
        ↓ 日文文字
[Claude Haiku API：翻譯成繁體中文]
        ↓
[tkinter 浮動視窗：顯示最近 3～5 句字幕]
```

## 資安原則

- `.env` 管理 `ANTHROPIC_API_KEY`，不進版控
- API key 不出現在程式碼或錯誤訊息
- `.env`、`*.db` 皆在 `.gitignore`

## 開發階段規劃

### Phase 1：音訊擷取 + STT（預估 3～4 天）

- [ ] 建立專案骨架（uv、`.venv`、`.gitignore`、`.env`）
- [ ] 用 `soundcard` 擷取系統輸出音訊（WASAPI Loopback）
- [ ] 串接 `faster-whisper large-v3`，GPU 加速確認
- [ ] VAD 斷句驗證（邊講邊切片，不會中途斷字）
- [ ] CLI 測試：播日文影片，終端機印出辨識結果

### Phase 2：翻譯串接（預估 2～3 天）

- [ ] 串接 Claude Haiku API
- [ ] 設計 Prompt：要求輸出純繁中譯文，不加解釋
- [ ] 處理連續輸入去重（避免同一句被翻譯兩次）
- [ ] CLI 測試：辨識 + 翻譯結果一起印出

### Phase 3：字幕視窗（預估 2～3 天）

- [ ] `tkinter` 浮動視窗：透明背景、置頂、可拖移
- [ ] 顯示最近 3～5 句（新句進、舊句淡出或捲動）
- [ ] 字體大小、顏色可在 `.env` 設定

### Phase 4：調校與優化（預估 3～5 天）

- [ ] 調整緩衝時間，平衡延遲與斷句品質
- [ ] 靜音偵測：無人說話時不送 API，節省費用
- [ ] 錯誤處理：API 超時、音訊裝置中斷
- [ ] 記錄翻譯 log（可選，`.txt` 或 SQLite）

**MVP 總時間線：約 2～3 週**

## 已知技術風險

| 風險 | 說明 | 應對 |
|---|---|---|
| 斷句問題 | 直播是連續音訊，需偵測說話停頓 | faster-whisper 內建 VAD，優先用這個 |
| 端對端延遲 | STT + 翻譯合計約 1～3 秒 | 對直播可接受，無法完全同步 |
| 直播雜訊 | BGM、音效可能觸發誤辨識 | VAD 閾值調高，過濾短片段 |
| API 費用 | Haiku 便宜但仍有成本 | 靜音偵測避免白送；記錄每日用量 |

## 進度記錄

| 日期 | 完成項目 |
|---|---|
| 2026-06-10 | 建立 README、規劃開發階段 |

## 下一步

開始 Phase 1：建立專案骨架，驗證 soundcard + faster-whisper GPU 可以在桌機上跑通。

## 開發工作流程

家用桌機為唯一開發與執行機器。

```powershell
# 啟動虛擬環境（建立後）
.venv\Scripts\activate

# 執行主程式（建立後）
.venv\Scripts\python.exe -m stream_caption
```


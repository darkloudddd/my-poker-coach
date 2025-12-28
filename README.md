# 🃏 My Poker Coach (我的撲克教練)

歡迎使用 **My Poker Coach**。這是一個基於 **GTO (賽局理論最佳化)** 的 AI 撲克教練系統，能夠根據您的手牌與當前局勢，提供最佳的決策建議 (下注、過牌、棄牌)。

## ✨ 系統特色

- **GTO 策略核心**：基於數學與賽局理論提供建議。
- **自然語言互動**：直接描述牌局狀況即可獲得分析。
- **簡易操作**：提供自動化腳本，無需複雜設定。

---

## 🚀 快速開始

我們為不同作業系統提供了 **「一鍵啟動」** 腳本，它會自動完成安裝、設定與啟動。

### 🪟 Windows 使用者

1. 雙擊執行 **`run_all.bat`**。
2. 依照指示輸入 API Key (僅首次需要)。
3. 程式將自動開啟瀏覽器進入教學介面。

---

### 🍎 Mac / Linux 使用者

請在終端機執行：

```bash
sh run_all.sh
```

程式將自動完成安裝並啟動。

---

## 📖 使用說明

在網頁介面的對話框中輸入牌局資訊，例如：

- 「我在6 max 急速桌，後手150bb的utg+1 open 3bb, 我在buttun 後手有100bb 手拿 KhTh選擇 3b 到 9bb, sb fold, bb fold, utg+1 call. flop Ks Tc 7d, 對手check, 此時我該 check 還是 bet?」

系統將會分析：
- 雙方範圍優勢 (Range Advantage)
- 建議行動與頻率 (GTO Strategy)

---

## 🛠️ 開發資訊

- **語言**: Python 3.9+
- **框架**: FastAPI
- **架構**:
    - `core/`: 核心基礎設施
        - `parser.py`: 自然語言解析器，將使用者輸入轉換為結構化資料
        - `config.py`: 系統全域設定
    - `features/`: 撲克邏輯特徵提取
        - `cards.py`: 撲克牌物件模型與基礎邏輯
        - `context.py`: 牌局上下文管理 (Context)
    - `strategy/`: 策略運算引擎
        - `engine.py`: 策略決策總入口
        - `gto.py`: 數學模型計算 (MDF, Bluff Ratio, Alpha)
        - `streets/`: 各條街 (Preflop/Flop/Turn/River) 的具體策略實現
    - `services/`: 外部服務整合
        - `llm_client.py`: 與 LLM (OpenAI) 的通訊介面
        - `prompts.py`: AI 角色設定與提示詞管理
    - `server.py`: FastAPI 應用程式入口與 API 定義
    - `agent.py`: 整合策略分析與自然語言生成的教練代理人

## 📄 License

MIT License

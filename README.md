# AI 題目生成器（支援 Kahoot、Wayground、Google Forms 及一鍵電郵分享）

這個專案是一個以 **Streamlit** 製作的教師工具：把教材（PDF/DOCX/TXT/PPTX/XLSX/圖片）轉成校內小測/課堂活動題目，並可一鍵匯出到 **Kahoot**、**Wayground** 或建立 **Google Forms Quiz**，亦支援把匯出檔案上載到 **Google Drive** 後以電郵分享。

---

## 主要功能

- **AI 生成新題目（單選 4 選 1）**：支援難度「基礎/標準/進階/混合」。citeturn160file177  
- **匯入現有題目（AI 協助整理）**：把老師現成題目拆成題幹/選項/答案，並標示「需教師確認」。citeturn160file177turn161search168  
- **重點段落標記**：上載教材後可勾選重點段落，提高貼題度。citeturn160file177  
- **匯出/分享**：
  - 下載 **Kahoot Excel**
  - 下載 **Wayground DOCX**
  - 一鍵建立 **Google Forms Quiz**
  - 將檔案上載到 **Google Drive** 後「一鍵電郵分享」citeturn160file177  
- **LLM 讀圖 OCR（可選）**：掃描/截圖/圖表/幾何題可用「多模態 LLM」讀圖抽字再出題（提示：DeepSeek 暫不支援影像輸入；建議 Grok/ChatGPT 等）。citeturn160file177turn161search168  

---

## 支援檔案類型

- 教材上載：`PDF / DOCX / TXT / PPTX / XLSX / PNG / JPG`citeturn160file177  
- LLM OCR（讀圖）：
  - 圖片：PNG/JPG
  - PDF：因 Token 限制，建議最多 **5 頁**（程式內提供「LLM OCR PDF頁數（Token限制，最多5頁）」選項）citeturn160file177  

---

## 快速開始（本機）

> 你可以用 Python 3.10+（建議 3.11）建立虛擬環境。

1. 建立虛擬環境並安裝套件：

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

2. 啟動：

```bash
streamlit run app.py
```

---

## 在 Streamlit Community Cloud 部署

1. 把 repo 推到 GitHub
2. 在 Streamlit Cloud 建立 App（Main file path 設為 `app.py`）
3. 在 Secrets 設定 AI Key / Google OAuth（見下文）
4. Deploy / Reboot

---

## AI API 設定（支援多供應商）

側邊欄可選：DeepSeek / OpenAI / Grok(xAI) / Azure OpenAI / 自訂（OpenAI 相容）。citeturn160file177  

- **必填**：API Key
- **OpenAI 相容**：Base URL + Model
- **Azure OpenAI**：Endpoint + Deployment + API Version

> 建議先用「🧪 一鍵測試 API（回覆 OK）」確認連線無誤。citeturn160file177turn161search168

---

## Google OAuth（建立 Google Form + Drive 電郵分享）

### 需要什麼？

- Google OAuth Client（Client ID / Client Secret）
- 你的 Streamlit App URL（用作 redirect URI）

### 怎樣用？

- 左側「🟦 Google 連接」登入後，會啟用：
  - 建立 Google Form Quiz
  - 上載匯出檔到 Drive 並分享至指定電郵citeturn160file177

---

## LLM 讀圖 OCR（補回功能）

### 什麼時候用？

- 掃描 PDF / 相片截圖（抽取到文字太少）
- 圖表、幾何、排版複雜（傳統 OCR 較難）citeturn160file177turn161search168

### 使用方式

1. 在「生成新題目」頁面勾選：**🖼️ 啟用 LLM 讀圖 OCR**
2. 設定「LLM OCR PDF頁數（Token限制，最多5頁）」
3. 上載教材；當抽字少於門檻時系統會自動用 LLM 抽字並顯示預覽citeturn160file177

> 提示：若你使用 DeepSeek，暫不支援影像輸入；請改用 Grok 或 ChatGPT 等多模態 LLM。citeturn160file177turn161search168

---

## 常見問題（Troubleshooting）

### 1) 介面沒有更新

- 確認 Streamlit Cloud 的 **Main file path** 是 `app.py`
- 確認 app 指向正確 branch
- 重新 Deploy / Reboot

### 2) 生成題目數量不足

- 可能是模型回傳少於指定數目或 JSON 格式不完整
- 建議：關閉快速模式、或更換模型再試

### 3) LLM OCR 沒有效果

- 確認你所選模型支援 image input
- PDF 頁數太多時容易超時或 token 超限：請把 OCR 頁數設為 3–5

---

## 開發者備忘（可選）

- `app.py`：Streamlit UI / 流程
- `services/llm_service.py`：LLM 呼叫、JSON 解析/容錯、LLM OCR helpers、匯入整理 helpersciteturn160file177turn161search168
- `extractors/`：教材抽取（含圖片/PDF 轉換供 LLM OCR 使用）citeturn160file177

---

## 授權

（如需開源授權，可在此加入 MIT/Apache-2.0 等授權文字。）

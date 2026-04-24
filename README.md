***

# 🏫 AI 多項選擇題題目生成器（AI Quiz Generator）

香港中學校本 AI 出題工具：上載教材（多格式＋OCR）、可選重點段落、一鍵生成四選一 MCQ，並匯出至 **Kahoot**／**Wayground DOCX**／**Google Forms（Quiz/Survey）**，支援 Google OAuth 及 Drive/Email 分享（可選）。 
***

## ✨ 主要功能

### 🪄 生成新題目（Generate）

*   上載教材：PDF / DOCX / TXT / PPTX / XLSX / PNG / JPG（可選 OCR、可選 Vision 讀圖流程）
*   **重點段落選擇**：可勾選保留段落，提高貼題度（預設全選）
*   科目＋難度＋題數設定（科目以分組方式顯示，避免長列表難找）
*   生成時提供 **進度條 + 狀態提示 + 防重複生成鎖**（避免老師狂按導致重複呼叫）
*   生成後可在表格中直接微調：題幹／選項／答案／需要教師確認等

### 📄 匯入現有題目（Import）

*   支援貼上或上載檔案（PDF/DOCX/TXT/PPTX/XLSX），可選「AI 協助整理」或本地備援拆題，並匯出/分享
*   
### 📤 匯出與分享

*   ⬇️ **Kahoot Excel**（匯入 Kahoot）
*   ⬇️ **Wayground DOCX**（校本試卷/練習格式）
*   🟦 **Google Forms（測驗 Quiz / 普通問卷 Survey）**：匯出設定集中於「Google Form 匯出設定」區域，避免重複的匯出區塊
*   📧（可選）上載到 Google Drive 後以電郵分享（需 Google OAuth）

***

## 🧠 AI 出題特色（校本取向）

*   以科目特性／常見誤概念／干擾項提示來提升 MCQ 質量（配置於 `subjects_config.yaml`）
*   後處理移除「根據本文/根據以上/according to passage」等不自然題幹，並標記需教師覆核

***

## 🗂️ 專案結構（概要）

> 實際資料夾可能因部署而略有調整；以下為核心模組概念。

*   `app.py`：主入口（`st.set_page_config` 置頂；Google OAuth callback；tab 切換 generate/import）
*   `ui/sidebar.py`：AI 設定（預設 DeepSeek；進階切換供應商、API 測試、OCR/Vision 模式）
*   `ui/pages_generate.py`：生成流程（抽取→重點段落→生成→編輯→匯出）
*   `ui/pages_import.py`：匯入流程（抽取→整理→編輯→匯出）.
*   `services/llm_service.py`：OpenAI-compatible 呼叫、JSON 修復、重試、ping、科目配置載入
*   `services/vision_service.py`：Vision 直接出題／Vision OCR（支援 OpenAI-compatible / Grok 等）
*   `services/google_oauth.py`：Google OAuth（state 暫存、redirect URI、credentials dict 化）
*   `services/google_forms_api.py`：建立 Google Form（Quiz/Survey，含評分與解釋）.
*   `exporters/`：Kahoot Excel / Wayground DOCX 匯出
*   `extractors/extract.py`：教材文字抽取＋可選 OCR＋（可選）Vision 圖片資料
*   
***

## ⚙️ 安裝與啟動（本地）

### 1) 安裝 Python 依賴

```bash
pip install -r requirements.txt
```

依賴包含 Streamlit、PyMuPDF、python-docx、openpyxl、python-pptx、pytesseract、Google API client 等。

### 2)（可選）安裝 OCR 系統依賴：Tesseract

*   macOS（例）

```bash
brew install tesseract tesseract-lang
```

*   Ubuntu / Debian（例）

```bash
sudo apt-get install tesseract-ocr tesseract-ocr-chi-tra tesseract-ocr-chi-sim
```

若不需要本地 OCR，可跳過。

### 3) 啟動

```bash
streamlit run app.py
```

`app.py` 已確保 `st.set_page_config()` 在所有 Streamlit 呼叫之前，避免啟動錯誤。

***

## 🔌 AI 設定（Sidebar）

*   預設使用 **DeepSeek**（校內若已配置內置 Key，老師可直接使用）
*   「⚙️ 進階設定」可切換其他供應商（OpenAI 相容、自訂、Grok、Azure 等）並提供「🧪 一鍵測試 API」。
*   OCR / Vision 模式可於進階區選擇（理科建議 Vision；DeepSeek 本身不支援 Vision 時請切換支援 Vision 的模型）。

***

## 🟦 Google 整合（可選）

### Google OAuth Scopes（最小權限）

*   建立/修改 Google Forms
*   在用戶 Drive 建立檔案（drive.file）

### secrets 設定（建議用 Streamlit Secrets）

建立 `.streamlit/secrets.toml`：

```toml
APP_URL = "http://localhost:8501"

# Google OAuth client（可用 dict 結構或 JSON 字串）
[google_oauth_client]
# ...（略）

# （可選）校內預設 DeepSeek Key
[deepseek]
api_key = "YOUR_DEEPSEEK_KEY"
```

Google OAuth 使用 `APP_URL` 作 redirect URI，部署後最穩定。

***

## 🧯 常見問題（Troubleshooting）

### 1) 更新後仍見舊錯誤／功能未生效

Streamlit 可能仍載入舊 module，請 **reboot / restart**（你已驗證重啟可解決）。

### 2) Google Form 匯出出現重複區塊

目前設計已將 Google Form 匯出集中於「Google Form 匯出設定」，並可關閉 export panel 的 Google Form 區塊以避免重複。

### 3) 匯出按鈕 key 重複（DuplicateElementKey）

請確保同一頁面中 button 的 `key` 唯一；本版本已將「設定區」按鈕 key 與 export panel 區分開。

***

## 🔒 私隱與使用守則（學校建議）

*   請勿上載含學生個人資料的文件（姓名、班別、學號等）。
*   AI 生成題目需教師覆核；系統會以 `needs_review`／驗證提示協助老師快速檢查。
*   Google OAuth Client Secret 屬敏感資料，切勿上傳至公開 repo。

***

## 📄 授權

本專案為校本內部工具，版權屬原開發者所有。

***

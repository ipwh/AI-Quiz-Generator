根據你所有的原始碼檔案，以下是完整重寫的 `README.md`：

***

```markdown
# 🧠 AI 出題系統（AI Quiz Generator）

香港中學校本 AI 出題工具，支援多種教材格式，一鍵生成 MCQ 題目，並直接匯出至 Kahoot、Wayground DOCX 或 Google Forms。

---

## ✨ 功能概覽

### 🪄 生成新題目
- 上載教材（PDF / DOCX / TXT / PPTX / XLSX / PNG / JPG）
- 可標記重點段落，提高出題貼題度
- 支援難度設定：基礎 / 標準 / 進階 / 混合
- AI 自動生成四選一 MCQ，並顯示品質摘要
- 支援「快速模式」（⚡ 較快輸出）

### 📄 匯入現有題目
- 貼上或上載現有題目（DOCX / TXT / PDF）
- AI 協助整理成標準格式（含自動推測答案）
- 本地備援拆題（無需 API 亦可使用）

### 📤 匯出與分享
- ⬇️ 下載 **Kahoot Excel**（直接匯入 Kahoot）
- ⬇️ 下載 **Wayground DOCX**（校本試卷格式）
- 🟦 一鍵建立 **Google Forms Quiz**
- 📧 透過 **Google Drive** 電郵分享匯出檔案

### 🗃️ 題庫管理（Google Drive）
- 題目存入 Google Drive JSON 題庫
- 支援多人共用題庫（設定 Drive 權限）

---

## 🏗️ 專案結構

```
├── app.py                        # 主程式入口
├── requirements.txt              # Python 依賴
├── packages.txt                  # 系統依賴（Streamlit Cloud 用）
│
├── extractors/
│   └── extract.py                # 文字擷取 + OCR + Vision data URL
│
├── services/
│   ├── llm_service.py            # AI 出題、OCR、Vision、xAI 偵測
│   ├── google_oauth.py           # Google OAuth 2.0 登入
│   ├── google_forms_api.py       # Google Forms Quiz 建立
│   ├── google_drive_bank.py      # Drive 題庫讀寫
│   └── cache_service.py          # 本地快取
│
├── core/
│   ├── question_mapper.py        # 題目資料結構轉換
│   └── validators.py             # 題目格式驗證
│
├── exporters/
│   ├── export_kahoot.py          # Kahoot Excel 匯出
│   └── export_wayground_docx.py  # Wayground DOCX 匯出
│
└── ui/  （可選模組化版）
    ├── sidebar.py
    ├── components_editor.py
    ├── components_export.py
    ├── pages_generate.py
    └── pages_import.py
```

---

## ⚙️ 安裝與啟動

### 1. 安裝依賴

```bash
pip install -r requirements.txt
```

### 2. 系統依賴（本地 OCR，可選）

```bash
# macOS
brew install tesseract tesseract-lang

# Ubuntu / Debian
sudo apt-get install tesseract-ocr tesseract-ocr-chi-tra tesseract-ocr-chi-sim
```

> 若不需要本地 OCR，跳過此步驟；系統會自動停用 Tesseract。

### 3. 啟動

```bash
streamlit run app.py
```

---

## 🔑 API 設定

在側邊欄選擇 AI 供應商並輸入 API Key：

| 供應商 | Base URL | 建議模型 |
|---|---|---|
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Grok (xAI) | `https://api.x.ai/v1` | 自動偵測最新型號 |
| Azure OpenAI | 自訂 Endpoint | 自訂 Deployment |
| 自訂（OpenAI 相容） | 自訂 | 自訂 |

> 按「🧪 一鍵測試 API」可驗證連線是否正常。

---

## 🟦 Google 整合（可選）

支援 Google OAuth 2.0，需在 Google Cloud Console 設定：

1. 建立 OAuth 2.0 憑證（Web Application）
2. 設定 Authorised Redirect URI（本地：`http://localhost:8501`）
3. 將以下環境變數或 Streamlit Secrets 填入：

```toml
# .streamlit/secrets.toml
GOOGLE_CLIENT_ID = "your-client-id"
GOOGLE_CLIENT_SECRET = "your-client-secret"
APP_URL = "http://localhost:8501"
```

啟用後可使用：
- 🟦 一鍵建立 Google Forms Quiz
- 📧 電郵分享 Kahoot / DOCX 至指定收件人
- 🗃️ 題目存入 Google Drive 題庫

---

## ☁️ 部署至 Streamlit Cloud

1. 將專案推送至 GitHub
2. 在 Streamlit Cloud 連接倉庫
3. 新增 `packages.txt`（系統依賴）：

```
tesseract-ocr
tesseract-ocr-chi-tra
tesseract-ocr-chi-sim
```

4. 在 Streamlit Cloud Secrets 填入 Google OAuth 設定

---

## 📚 支援科目

中國語文、英國語文、數學、公民與社會發展、科學、物理、化學、生物、地理、歷史、中國歷史、經濟、資訊及通訊科技（ICT）、企業會計與財務概論、旅遊與款待、宗教

---

## 🗒️ 注意事項

- 題目生成需消耗 AI API Token，建議開啟「⚡ 快速模式」節省成本
- 含掃描頁 / 圖表的 PDF 建議啟用 LLM Vision 讀圖出題（需支援 Vision 的型號）
- 所有帶 `⚠️ 需教師確認` 的題目請老師在匯出前核對答案
- Google OAuth Client Secret 屬敏感資料，切勿上傳至公開 GitHub

---

## 📄 授權

本專案為校本內部工具，版權屬原開發者所有。
```

***


- **完整功能說明**（生成、匯入、匯出、Drive 題庫） [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/15954081/3b5f1c8c-d9d1-4d4c-86f3-756f06b4dd30/google_drive_bank.py)
- **專案結構對照**（你的實際資料夾佈局） [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/15954081/a310a0f2-954d-4368-9f70-a5c4859d91df/pages_generate.py)
- **本地安裝 + Streamlit Cloud 部署** 兩套流程 [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/15954081/694e67cf-31fa-44a5-822f-6db549b63fd7/requirements.txt)
- **API 供應商對照表**（包括 xAI 自動偵測） [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/15954081/bac7e41b-a93a-45c7-b208-56c4055d44e0/sidebar.py)
- **Google OAuth 設定指引** [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/15954081/42695d6c-23b8-4bc5-bb58-a3e2dc14216f/components_export.py)

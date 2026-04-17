# 香港中學 AI 題目生成器（多 API｜Google Forms 直出｜無 OCR）

## 功能
- 🪄 AI 生成新題目：上載 PDF/DOCX/TXT/PPTX/XLSX 生成 4 選 1
- 📄 匯入現有題目：貼上或上載 DOCX/TXT 自動載入後整理成題目
- 匯出：
  - Kahoot Excel
  - Wayground DOCX（只輸出問題/選項/答案 A-D，不輸出解說）
  - Google Forms：**一鍵建立 Google Form Quiz（需 Google OAuth）**

## 無 OCR
- 本版本已移除 OCR，因此不接受圖片檔。

## Google Forms 一鍵建立（方案 B3）
本專案使用 Google Forms API：先建立表單，再用 batchUpdate 將表單設為 quiz 並加入題目。citeturn72search34turn72search36

### 你需要做一次的 Google Cloud 設定
1. 建立 Google Cloud Project
2. 啟用 **Google Forms API**
3. 設定 OAuth consent screen
4. 建立 OAuth Client ID（Web application）
5. 在 Streamlit Secrets 放入 OAuth client 設定（見下文）

### Streamlit Secrets
在 Streamlit Community Cloud 的 App 設定頁面加入 secrets：

```toml
APP_URL = "https://<你的app>.streamlit.app"

[google_oauth_client]
# 直接貼 Google OAuth client JSON 的內容（client_id, client_secret, auth_uri, token_uri, redirect_uris 等）
```

> Redirect URI 必須包含：`APP_URL`（如上）。

## 本機運行
```bash
pip install -r requirements.txt
python -m streamlit run app.py
```

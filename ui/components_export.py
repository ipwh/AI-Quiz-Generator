import streamlit as st
import pandas as pd
from exporters.export_kahoot import export_kahoot
from exporters.export_wayground_docx import export_wayground_docx
from services.google_forms_api import create_quiz_form
from services.google_oauth import credentials_from_dict
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io


def drive_service(creds):
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def upload_bytes_to_drive(creds, filename: str, mimetype: str, data_bytes: bytes) -> dict:
    service = drive_service(creds)
    media = MediaIoBaseUpload(io.BytesIO(data_bytes), mimetype=mimetype, resumable=False)
    meta = {"name": filename}
    return service.files().create(body=meta, media_body=media, fields="id, webViewLink").execute()


def share_file_to_emails(creds, file_id: str, emails: list, role: str = "reader"):
    service = drive_service(creds)
    for email in emails:
        email = str(email).strip()
        if not email:
            continue
        body = {"type": "user", "role": role, "emailAddress": email}
        service.permissions().create(fileId=file_id, body=body, sendNotificationEmail=True).execute()


def render_export_panel(selected_df: pd.DataFrame, subject: str, google_creds_dict, prefix: str):
    if selected_df is None or selected_df.empty:
        st.warning("⚠️ 尚未選擇任何題目（請勾選『匯出』欄）。")
        return

    kahoot_bytes = export_kahoot(selected_df)
    docx_bytes = export_wayground_docx(selected_df, subject)

    c1, c2 = st.columns(2)
    with c1:
        st.download_button("⬇️ Kahoot Excel", kahoot_bytes, "kahoot.xlsx", key=f"dl_kahoot_{prefix}")
    with c2:
        st.download_button("⬇️ Wayground DOCX", docx_bytes, "wayground.docx", key=f"dl_docx_{prefix}")

    # Google Form
    if google_creds_dict:
        if st.button("🟦 一鍵建立 Google Form Quiz", key=f"btn_form_{prefix}"):
            try:
                with st.spinner("🟦 正在建立 Google Form…"):
                    creds = credentials_from_dict(google_creds_dict)
                    result = create_quiz_form(creds, f"{subject} Quiz", selected_df)
                st.session_state[f"form_result_{prefix}"] = result
                st.success("✅ 已建立 Google Form")
            except Exception as e:
                st.error("⚠️ 建立 Google Form 失敗。")
                st.exception(e)

        r = st.session_state.get(f"form_result_{prefix}")
        if r:
            st.write("編輯連結：", r.get("editUrl"))
            st.write("發佈連結：", r.get("responderUrl") or "（未提供 responderUri）")

    # Drive share
    st.markdown("### 📧 一鍵電郵分享匯出檔（Google Drive）")
    if not google_creds_dict:
        st.info("請先在左側登入 Google，才可用電郵分享檔案。")
        return

    emails_text = st.text_input("收件人電郵（多個用逗號分隔）", value="", key=f"emails_{prefix}")
    emails = [e.strip() for e in emails_text.split(",") if e.strip()]

    colA, colB = st.columns(2)
    with colA:
        if st.button("📧 分享 Kahoot Excel", key=f"btn_share_kahoot_{prefix}"):
            creds = credentials_from_dict(google_creds_dict)
            uploaded = upload_bytes_to_drive(
                creds,
                filename=f"{subject}_kahoot.xlsx",
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                data_bytes=kahoot_bytes,
            )
            share_file_to_emails(creds, uploaded["id"], emails, role="reader")
            st.success("✅ 已分享 Kahoot 檔案")
            st.write("Drive 連結：", uploaded.get("webViewLink"))

    with colB:
        if st.button("📧 分享 Wayground DOCX", key=f"btn_share_docx_{prefix}"):
            creds = credentials_from_dict(google_creds_dict)
            uploaded = upload_bytes_to_drive(
                creds,
                filename=f"{subject}_wayground.docx",
                mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                data_bytes=docx_bytes,
            )
            share_file_to_emails(creds, uploaded["id"], emails, role="reader")
            st.success("✅ 已分享 Wayground 檔案")
            st.write("Drive 連結：", uploaded.get("webViewLink"))
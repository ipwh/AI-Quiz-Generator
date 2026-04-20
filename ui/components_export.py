import io
import streamlit as st
import pandas as pd

from exporters.export_kahoot import export_kahoot_excel          # ✅ 修正：原為 export_kahoot（不存在）
from exporters.export_wayground_docx import export_wayground_docx
from services.google_forms_api import create_quiz_form
from services.google_oauth import credentials_from_dict

from core.question_mapper import editor_df_to_items, items_to_export_df
from core.validators import validate_questions, summarize_report

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload


def _drive_service(creds):
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _upload_bytes_to_drive(creds, filename: str, mimetype: str, data_bytes: bytes) -> dict:
    service = _drive_service(creds)
    media = MediaIoBaseUpload(io.BytesIO(data_bytes), mimetype=mimetype, resumable=False)
    meta = {"name": filename}
    return service.files().create(body=meta, media_body=media, fields="id, webViewLink").execute()


def _share_file_to_emails(creds, file_id: str, emails: list, role: str = "reader"):
    service = _drive_service(creds)
    for email in emails:
        email = str(email).strip()
        if not email:
            continue
        body = {"type": "user", "role": role, "emailAddress": email}
        service.permissions().create(fileId=file_id, body=body, sendNotificationEmail=True).execute()


def render_export_panel(selected_df: pd.DataFrame, subject: str, google_creds_dict, prefix: str = "generate"):
    """Export panel with validator quality gate (lenient default)."""

    if selected_df is None or selected_df.empty:
        st.warning("⚠️ 尚未選擇任何題目（請勾選『匯出』欄）。")
        return

    items = editor_df_to_items(selected_df, default_subject=subject, source=prefix)
    report = validate_questions(items)
    bad_count, err_counts = summarize_report(report)

    if bad_count:
        st.warning(f"⚠️ 有 {bad_count} 題未通過檢查。建議先修正，或選擇只匯出通過檢查的題目。")
        with st.expander("🔎 查看檢查統計與問題清單", expanded=False):
            st.write("常見問題統計：")
            st.json(err_counts)
            bad_rows = [r for r in report if not r.get("ok")]
            st.write("未通過的題目（前 20 題）：")
            st.dataframe(pd.DataFrame(bad_rows)[:20], use_container_width=True)
    else:
        st.success("✅ 所有已選題目均通過檢查")

    default_mode = "只匯出通過檢查的題目（建議）"
    mode = st.radio(
        "匯出模式",
        [default_mode, "仍然匯出包含問題的題目（不建議）"],
        index=0, horizontal=True,
        key=f"export_mode_{prefix}",
    )

    ok_items = [it for it, r in zip(items, report) if r.get("ok")]
    export_items = items if mode != default_mode else ok_items

    if not export_items:
        st.error("⚠️ 沒有任何題目可匯出（全部未通過檢查）。請先修正或降低匯出限制。")
        return

    export_df = items_to_export_df(export_items)

    # ✅ 修正：使用正確的函數名稱 export_kahoot_excel
    kahoot_bytes = export_kahoot_excel(export_df)
    docx_bytes = export_wayground_docx(export_df, subject)

    c1, c2 = st.columns(2)
    with c1:
        st.download_button("⬇️ Kahoot Excel", kahoot_bytes, f"{subject}_kahoot.xlsx", key=f"dl_kahoot_{prefix}")
    with c2:
        st.download_button("⬇️ Wayground DOCX", docx_bytes, f"{subject}_wayground.docx", key=f"dl_docx_{prefix}")

    if google_creds_dict:
        if st.button("🟦 一鍵建立 Google Form Quiz", key=f"btn_form_{prefix}"):
            try:
                with st.spinner("🟦 正在建立 Google Form…"):
                    creds = credentials_from_dict(google_creds_dict)
                    result = create_quiz_form(creds, f"{subject} Quiz", export_df)
                    st.session_state[f"form_result_{prefix}"] = result
                    st.success("✅ 已建立 Google Form")
            except Exception as e:
                st.error("⚠️ 建立 Google Form 失敗。")
                st.exception(e)

        r = st.session_state.get(f"form_result_{prefix}")
        if r:
            st.markdown(f"🔗 **編輯連結：** {r.get('editUrl')}")
            st.markdown(f"👥 **作答連結：** {r.get('responderUrl') or '（未提供 responderUri）'}")

    st.markdown("### 📧 一鍵電郵分享匯出檔（Google Drive）")
    if not google_creds_dict:
        st.info("請先在左側登入 Google，才可用電郵分享檔案。")
        return

    emails_text = st.text_input("收件人電郵（多個用逗號分隔）", value="", key=f"emails_{prefix}")
    emails = [e.strip() for e in emails_text.split(",") if e.strip()]

    colA, colB = st.columns(2)
    with colA:
        if st.button("📧 分享 Kahoot Excel", key=f"btn_share_kahoot_{prefix}"):
            if not emails:
                st.warning("請先輸入至少一個電郵。")
            else:
                creds = credentials_from_dict(google_creds_dict)
                uploaded = _upload_bytes_to_drive(
                    creds, filename=f"{subject}_kahoot.xlsx",
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    data_bytes=kahoot_bytes,
                )
                _share_file_to_emails(creds, uploaded["id"], emails)
                st.success("✅ 已分享 Kahoot 檔案")
                st.markdown(f"🔗 Drive 連結：{uploaded.get('webViewLink')}")

    with colB:
        if st.button("📧 分享 Wayground DOCX", key=f"btn_share_docx_{prefix}"):
            if not emails:
                st.warning("請先輸入至少一個電郵。")
            else:
                creds = credentials_from_dict(google_creds_dict)
                uploaded = _upload_bytes_to_drive(
                    creds, filename=f"{subject}_wayground.docx",
                    mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    data_bytes=docx_bytes,
                )
                _share_file_to_emails(creds, uploaded["id"], emails)
                st.success("✅ 已分享 Wayground 檔案")
                st.markdown(f"🔗 Drive 連結：{uploaded.get('webViewLink')}")

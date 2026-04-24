# ui/components_export.py
from __future__ import annotations
import io
import streamlit as st
import pandas as pd

from exporters.export_kahoot import export_kahoot_excel
from exporters.export_wayground_docx import export_wayground_docx
from services.google_forms_api import create_form
from services.google_oauth import credentials_from_dict
from core.question_mapper import editor_df_to_items, items_to_export_df
from core.validators import validate_questions, summarize_report

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
    _GOOGLE_API_OK = True
except Exception:
    build = None
    MediaIoBaseUpload = None
    _GOOGLE_API_OK = False


def _drive_service(creds):
    if not _GOOGLE_API_OK:
        raise RuntimeError("缺少 google-api-python-client")
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
        service.permissions().create(
            fileId=file_id, body=body, sendNotificationEmail=True
        ).execute()


def render_export_panel(
    selected_df: pd.DataFrame,
    subject: str,
    google_creds_dict,
    prefix: str = "generate",
):
    if selected_df is None or selected_df.empty:
        st.warning("尚未選擇任何題目（請勾選『匯出』欄）。")
        return

    items = editor_df_to_items(selected_df, default_subject=subject, source=prefix)
    report = validate_questions(items)
    bad_count, err_counts = summarize_report(report)

    if bad_count:
        st.warning(f"有 {bad_count} 題未通過檢查。建議先修正，或只匯出通過檢查的題目。")
        with st.expander("查看檢查統計與問題清單", expanded=False):
            st.json(err_counts)
            bad_rows = [r for r in report if not r.get("ok")]
            st.dataframe(pd.DataFrame(bad_rows)[:20], use_container_width=True)
    else:
        st.success("所有已選題目均通過檢查")

    default_mode = "只匯出通過檢查的題目（建議）"
    mode = st.radio(
        "匯出範圍",
        [default_mode, "仍然匯出包含問題的題目（不建議）"],
        index=0,
        horizontal=True,
        key=f"export_mode_{prefix}",
    )

    ok_items = [it for it, r in zip(items, report) if r.get("ok")]
    export_items = items if mode != default_mode else ok_items

    if not export_items:
        st.error("沒有任何題目可匯出（全部未通過檢查）。")
        return

    export_df = items_to_export_df(export_items)

    # --------------------------------------------------
    # Download buttons: Kahoot + Wayground
    # --------------------------------------------------
    kahoot_bytes = export_kahoot_excel(export_df)
    docx_bytes = export_wayground_docx(export_df, subject)

    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "Kahoot Excel",
            kahoot_bytes,
            f"{subject}_kahoot.xlsx",
            key=f"dl_kahoot_{prefix}",
        )
    with c2:
        st.download_button(
            "Wayground DOCX",
            docx_bytes,
            f"{subject}_wayground.docx",
            key=f"dl_docx_{prefix}",
        )

    # --------------------------------------------------
    # Google Form export
    # --------------------------------------------------
    if google_creds_dict:
        st.markdown("### Google Form 匯出")

        col_l, col_r = st.columns(2)

        with col_l:
            form_mode = st.radio(
                "匯出模式",
                ["測驗模式（Quiz）", "普通問卷（Survey）"],
                index=0,
                key=f"gform_mode_{prefix}",
                help=(
                    "測驗模式：含正確答案、評分及解釋，學生提交後可即時查閱成績。\n"
                    "普通問卷：只有題目和選項，不設答案評分。"
                ),
            )
            quiz_mode = form_mode.startswith("測驗")

        with col_r:
            if quiz_mode:
                points = st.number_input(
                    "每題分數",
                    min_value=1,
                    max_value=10,
                    value=1,
                    step=1,
                    key=f"gform_points_{prefix}",
                )
                show_exp = st.checkbox(
                    "答錯時顯示解釋說明",
                    value=True,
                    key=f"gform_show_exp_{prefix}",
                    help="學生答錯後可即時看到 AI 生成的解釋，有助鞏固學習。",
                )
            else:
                points = 1
                show_exp = False
                st.caption("普通問卷不設評分及解釋。")

        form_label = "測驗模式 Google Form" if quiz_mode else "普通問卷 Google Form"
        btn_icon = "📝" if quiz_mode else "📋"

        if st.button(
            f"{btn_icon} 一鍵建立 {form_label}",
            key=f"btn_form_{prefix}",
        ):
            try:
                with st.spinner(f"正在建立 {form_label}..."):
                    creds = credentials_from_dict(google_creds_dict)
                    result = create_form(
                        creds=creds,
                        title=f"{subject} {'Quiz' if quiz_mode else 'Survey'}",
                        df=export_df,
                        quiz_mode=quiz_mode,
                        points_per_question=int(points),
                        show_explanation=show_exp,
                    )
                    st.session_state[f"form_result_{prefix}"] = result
                st.success(f"已建立 {form_label}")
            except Exception as e:
                st.error("建立 Google Form 失敗。")
                st.exception(e)

        r = st.session_state.get(f"form_result_{prefix}")
        if r:
            edit_url = r.get("editUrl", "")
            resp_url = r.get("responderUrl", "")
            st.markdown(f"**編輯連結（教師）：** [{edit_url}]({edit_url})")
            if resp_url:
                st.markdown(f"**作答連結（學生）：** [{resp_url}]({resp_url})")
            else:
                st.caption("作答連結未提供，請從編輯連結內複製。")

    # --------------------------------------------------
    # Email share via Google Drive
    # --------------------------------------------------
    st.markdown("### 電郵分享匯出檔（Google Drive）")

    if not _GOOGLE_API_OK:
        st.info(
            "未安裝 google-api-python-client：仍可下載 Excel/DOCX、建立 Google Form；"
            "但 Drive 上傳及電郵分享不可用。"
        )
        return

    if not google_creds_dict:
        st.info("請先在頁面頂部連接 Google 帳戶，才能使用電郵分享功能。")
        return

    emails_text = st.text_input(
        "收件人電郵（多個用逗號分隔）",
        value="",
        key=f"emails_{prefix}",
        placeholder="xxx@pochiu.edu.hk",
    )
    emails = [e.strip() for e in emails_text.split(",") if e.strip()]

    colA, colB = st.columns(2)

    with colA:
        if st.button("分享 Kahoot Excel", key=f"btn_share_kahoot_{prefix}"):
            if not emails:
                st.warning("請先輸入至少一個電郵。")
            else:
                try:
                    creds = credentials_from_dict(google_creds_dict)
                    uploaded = _upload_bytes_to_drive(
                        creds,
                        filename=f"{subject}_kahoot.xlsx",
                        mimetype=(
                            "application/vnd.openxmlformats-officedocument"
                            ".spreadsheetml.sheet"
                        ),
                        data_bytes=kahoot_bytes,
                    )
                    _share_file_to_emails(creds, uploaded["id"], emails)
                    st.success("已分享 Kahoot 檔案")
                    st.markdown(f"Drive 連結：{uploaded.get('webViewLink')}")
                except Exception as e:
                    st.error("分享失敗")
                    st.exception(e)

    with colB:
        if st.button("分享 Wayground DOCX", key=f"btn_share_docx_{prefix}"):
            if not emails:
                st.warning("請先輸入至少一個電郵。")
            else:
                try:
                    creds = credentials_from_dict(google_creds_dict)
                    uploaded = _upload_bytes_to_drive(
                        creds,
                        filename=f"{subject}_wayground.docx",
                        mimetype=(
                            "application/vnd.openxmlformats-officedocument"
                            ".wordprocessingml.document"
                        ),
                        data_bytes=docx_bytes,
                    )
                    _share_file_to_emails(creds, uploaded["id"], emails)
                    st.success("已分享 Wayground 檔案")
                    st.markdown(f"Drive 連結：{uploaded.get('webViewLink')}")
                except Exception as e:
                    st.error("分享失敗")
                    st.exception(e)

import streamlit as st
import streamlit.components.v1 as components
from services.google_drive_picker import (
    extract_file_id,
    download_file,
    list_recent_files,
)
from services.google_oauth import credentials_from_dict


# Google Picker API 需要 OAuth access token + API Key（瀏覽器端）
# 若你有 Google Picker API Key，填在 secrets.toml：
# GOOGLE_PICKER_API_KEY = "AIza..."
def _picker_api_key() -> str:
    try:
        import streamlit as st
        return st.secrets.get("GOOGLE_PICKER_API_KEY", "")
    except Exception:
        return ""


def _get_access_token(creds_dict: dict) -> str:
    """從 credentials dict 取得 access token。"""
    try:
        creds = credentials_from_dict(creds_dict)
        return creds.token or ""
    except Exception:
        return ""


def render_drive_file_picker(creds_dict: dict) -> dict | None:
    """
    A）Google Drive File Picker 彈出視窗。
    回傳 {"id": ..., "name": ...} 或 None。
    需要 GOOGLE_PICKER_API_KEY 在 secrets.toml。
    """
    api_key = _picker_api_key()
    access_token = _get_access_token(creds_dict)

    if not api_key:
        st.info("💡 未設定 GOOGLE_PICKER_API_KEY，無法使用視窗選檔。請改用下方「貼上連結」或「最近檔案」功能。")
        return None

    if not access_token:
        st.warning("請先登入 Google。")
        return None

    picker_html = f"""
    <script>
    var pickerApiLoaded = false;
    var oauthToken = '{access_token}';
    var developerKey = '{api_key}';

    function loadPicker() {{
        gapi.load('picker', {{'callback': onPickerApiLoad}});
    }}

    function onPickerApiLoad() {{
        pickerApiLoaded = true;
    }}

    function createPicker() {{
        if (pickerApiLoaded && oauthToken) {{
            var view = new google.picker.View(google.picker.ViewId.DOCS);
            view.setMimeTypes(
                'application/pdf,' +
                'application/vnd.google-apps.document,' +
                'application/vnd.google-apps.presentation,' +
                'application/vnd.google-apps.spreadsheet,' +
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document,' +
                'text/plain,image/png,image/jpeg'
            );
            var picker = new google.picker.PickerBuilder()
                .enableFeature(google.picker.Feature.NAV_HIDDEN)
                .setAppId('{api_key}')
                .setOAuthToken(oauthToken)
                .addView(view)
                .setDeveloperKey(developerKey)
                .setCallback(pickerCallback)
                .build();
            picker.setVisible(true);
        }}
    }}

    function pickerCallback(data) {{
        if (data.action == google.picker.Action.PICKED) {{
            var file = data.docs[0];
            window.parent.postMessage(
                {{type: 'DRIVE_PICKED', id: file.id, name: file.name}},
                '*'
            );
        }}
    }}
    </script>
    <script src="https://apis.google.com/js/api.js?onload=loadPicker"></script>
    <button onclick="createPicker()"
        style="padding:8px 18px;background:#4285F4;color:white;border:none;
               border-radius:6px;cursor:pointer;font-size:14px;">
        📂 開啟 Google Drive 選檔視窗
    </button>
    """
    components.html(picker_html, height=60)
    st.caption("選檔後檔案 ID 會自動填入下方欄位（若瀏覽器允許 postMessage）。")
    return None


def render_drive_input_panel(creds_dict: dict) -> bytes | None:
    """
    完整 Drive 教材上載面板，包含 A / B / C 三種方式。
    回傳下載好的 (bytes, filename, ext) 或 None。
    """
    if not creds_dict:
        st.info("請先在左側登入 Google，才能從 Drive 上載教材。")
        return None, None, None

    st.markdown("### ☁️ 從 Google Drive 上載教材")

    tab_a, tab_b, tab_c = st.tabs([
        "📂 A）選檔視窗",
        "🔗 B）貼上連結／ID",
        "📋 C）最近檔案",
    ])

    selected_id = None
    selected_name = ""

    # ── A）File Picker ──────────────────────────────
    with tab_a:
        st.caption("點擊按鈕，從 Google Drive 視窗選取教材。")
        render_drive_file_picker(creds_dict)

        # 手動輸入 fallback（Picker postMessage 在 Streamlit iframe 受限）
        st.caption("📌 若按鈕未能自動填入，請複製 Drive 分享連結，貼到「B）貼上連結」頁。")

    # ── B）貼上連結 / ID ─────────────────────────────
    with tab_b:
        st.caption("貼上 Google Drive 分享連結或檔案 ID。")
        link_input = st.text_input(
            "Drive 連結或檔案 ID",
            placeholder="https://drive.google.com/file/d/xxxxx/view  或  直接貼上 ID",
            key="drive_link_input",
        )
        if link_input.strip():
            try:
                selected_id = extract_file_id(link_input.strip())
                st.success(f"✅ 識別到檔案 ID：`{selected_id}`")
            except ValueError as e:
                st.error(str(e))

    # ── C）最近檔案清單 ───────────────────────────────
    with tab_c:
        st.caption("顯示你 Google Drive 最近修改的教材檔案（最多 30 個）。")

        if st.button("🔄 載入最近檔案", key="btn_load_recent_drive"):
            with st.spinner("正在讀取 Drive 檔案清單…"):
                try:
                    creds = credentials_from_dict(creds_dict)
                    files = list_recent_files(creds, max_results=30)
                    st.session_state["drive_recent_files"] = files
                except Exception as e:
                    st.error(f"讀取失敗：{e}")

        files = st.session_state.get("drive_recent_files", [])
        if files:
            options = {
                f["name"] + f"  （{f.get('modifiedTime','')[:10]}）": f["id"]
                for f in files
            }
            chosen_label = st.selectbox(
                "選擇檔案",
                list(options.keys()),
                key="drive_recent_select",
            )
            if chosen_label:
                selected_id = options[chosen_label]
                selected_name = chosen_label.split("  （")[0]
                st.success(f"✅ 已選：{selected_name}  （ID: `{selected_id}`）")

    # ── 下載選定檔案 ──────────────────────────────────
    if selected_id:
        if st.button("⬇️ 從 Drive 下載並載入教材", key="btn_drive_download"):
            with st.spinner("正在從 Google Drive 下載教材…"):
                try:
                    creds = credentials_from_dict(creds_dict)
                    data, filename, ext = download_file(creds, selected_id)
                    st.session_state["drive_file_bytes"] = data
                    st.session_state["drive_file_name"] = filename
                    st.session_state["drive_file_ext"] = ext
                    st.success(f"✅ 已下載：{filename}（{len(data):,} bytes）")
                except Exception as e:
                    st.error(f"下載失敗：{e}")
                    st.exception(e)

    # 回傳已下載的檔案
    if st.session_state.get("drive_file_bytes"):
        return (
            st.session_state["drive_file_bytes"],
            st.session_state["drive_file_name"],
            st.session_state["drive_file_ext"],
        )

    return None, None, None

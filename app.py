import streamlit as st

from core.session_state import init_session_state
from ui.sidebar import render_sidebar
from ui.pages_generate import render_generate_tab
from ui.pages_import import render_import_tab

from services.google_oauth import (
    oauth_is_configured,
    get_auth_url,
    exchange_code_for_credentials,
    credentials_to_dict,
)
from services.llm_service import (
    generate_questions,
    assist_import_questions,
    parse_import_questions_locally,
)


def handle_oauth_callback():
    params = st.query_params
    if oauth_is_configured() and "code" in params and not st.session_state.google_creds:
        code = params.get("code")
        state = params.get("state")
        if isinstance(code, list):
            code = code[0]
        if isinstance(state, list):
            state = state[0]
        creds = exchange_code_for_credentials(code=code, returned_state=state)
        st.session_state.google_creds = credentials_to_dict(creds)
        st.query_params.clear()
        st.rerun()


def render_google_sidebar():
    st.sidebar.header("🟦 Google 連接（Google Forms / Drive 一鍵分享）")
    if not oauth_is_configured():
        st.sidebar.warning("⚠️ 尚未設定 Google OAuth（Secrets: google_oauth_client + APP_URL）")
    else:
        if st.session_state.google_creds:
            st.sidebar.success("✅ 已連接 Google")
            if st.sidebar.button("🔒 登出 Google", key="btn_logout_google"):
                st.session_state.google_creds = None
                st.rerun()
        else:
            st.sidebar.link_button("🔐 連接 Google（登入）", get_auth_url())
            st.sidebar.caption("提示：請以學校電郵登入，方便統一管理與分享。")


def main():
    st.set_page_config(page_title="AI 題目生成器", layout="wide")
    st.title("🏫 AI 題目生成器（支援Kahoot、Wayground、Google Forms及一鍵電郵分享）")

    init_session_state()
    handle_oauth_callback()

    # sidebar：Google + AI + 出題設定
    render_google_sidebar()
    ctx = render_sidebar()

    # 注入 service funcs（避免 ui 層 import 太多 service）
    ctx["generate_questions"] = generate_questions
    ctx["assist_import_questions"] = assist_import_questions
    ctx["parse_import_questions_locally"] = parse_import_questions_locally

    with st.expander("🧭 使用流程（建議）", expanded=True):
        st.markdown(
            "\n".join([
                "**🪄 生成新題目（推薦）**",
                "1. 左側完成：Google 登入（可選）＋設定 AI API",
                "2. 選科目、難度、題目數目",
                "3. 上載教材 →（可選）標記重點段落",
                "4. 按「生成題目」→ 在表格內微調題幹/選項/答案",
                "5. 勾選要匯出的題目 → 匯出 / 建 Google Form / 電郵分享",
                "",
                "**📄 匯入現有題目**",
                "1. 上載/貼上題目內容 →（可選）啟用 AI 協助整理",
                "2. 按「整理並轉換」→ 在表格內校對答案",
                "3. 匯出 / 建 Google Form / 電郵分享",
            ])
        )

    tab_generate, tab_import = st.tabs(["🪄 生成新題目", "📄 匯入現有題目"])
    with tab_generate:
        render_generate_tab(ctx)
    with tab_import:
        render_import_tab(ctx)


if __name__ == "__main__":
    main()
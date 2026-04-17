import json
import streamlit as st
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials

# 需要的 scopes：建立/修改 Google Forms + 在用戶 Drive 建立文件
SCOPES = [
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/drive.file",
]


def oauth_is_configured() -> bool:
    """Streamlit secrets 內必須有 google_oauth_client"""
    return "google_oauth_client" in st.secrets


def get_redirect_uri() -> str:
    """
    用 Streamlit Secrets 的 APP_URL 作 redirect URI（部署後固定最穩）。
    - Streamlit Cloud: https://<app>.streamlit.app
    - 本機測試: http://localhost:8501
    """
    app_url = str(st.secrets.get("APP_URL", "")).strip().rstrip("/")
    if app_url:
        return app_url
    return "http://localhost:8501"


def _load_google_client_config() -> dict:
    """
    從 st.secrets 讀取 google_oauth_client，並轉成符合 google-auth-oauthlib 的 client secrets format。
    必須有最外層 web 或 installed。[1](https://cloud.google.com/use-cases/ocr)[2](https://zhuanlan.zhihu.com/p/1964739506629490036)
    """
    client = st.secrets["google_oauth_client"]

    # secrets 常用做法：以多行字串存 JSON，所以要 json.loads 轉 dict。[3](https://docs.ucloud.cn/modelverse/api_doc/text_api/deepseek-ocr?id=deepseek-ocr-%e6%a8%a1%e5%9e%8b)[4](blob:https://m365.cloud.microsoft/416c93ef-4252-48fd-a0d4-ad845993cab4)
    if isinstance(client, str):
        client = json.loads(client)

    # 若只貼了 web 內部，幫你包回正確格式
    if "web" not in client and "installed" not in client:
        client = {"web": client}

    return client


def build_google_oauth_flow(redirect_uri: str, code_verifier: str | None = None) -> Flow:
    """
    建立 OAuth Flow（含 PKCE）。
    Flow 支援 code_verifier / autogenerate_code_verifier 參數。[1](https://cloud.google.com/use-cases/ocr)
    """
    client_config = _load_google_client_config()

    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
        autogenerate_code_verifier=(code_verifier is None),
    )
    return flow


def get_or_create_auth_url() -> str:
    """
    只在第一次生成登入連結（避免每次 rerun 覆蓋 state / code_verifier）。
    """
    # 如果之前已生成過，直接重用
    if (
        st.session_state.get("google_oauth_auth_url")
        and st.session_state.get("google_oauth_state")
        and st.session_state.get("google_oauth_code_verifier")
    ):
        return st.session_state["google_oauth_auth_url"]

    redirect_uri = get_redirect_uri()
    flow = build_google_oauth_flow(redirect_uri)

    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        code_challenge_method="S256",
    )

    # 保存（最關鍵）
    st.session_state["google_oauth_auth_url"] = auth_url
    st.session_state["google_oauth_state"] = state
    st.session_state["google_oauth_code_verifier"] = flow.code_verifier

    return auth_url


def clear_oauth_temp_state():
    """登入完成或失敗後，可清走暫存（讓下次重新生成乾淨的 auth_url/state/verifier）"""
    for k in [
        "google_oauth_auth_url",
        "google_oauth_state",
        "google_oauth_code_verifier",
    ]:
        if k in st.session_state:
            st.session_state.pop(k, None)


def exchange_code_for_credentials(code: str, returned_state: str | None = None) -> Credentials:
    """
    用 callback 回來的 code 換取 Credentials。
    會檢查 state 並使用保存的 code_verifier（PKCE），否則會 invalid_grant Missing code verifier。[1](https://cloud.google.com/use-cases/ocr)
    """
    expected_state = st.session_state.get("google_oauth_state")
    verifier = st.session_state.get("google_oauth_code_verifier")

    if expected_state and returned_state and returned_state != expected_state:
        raise ValueError("state 不匹配：請重新按『連接 Google（登入）』。")

    if not verifier:
        raise ValueError("缺少 code_verifier：請重新按『連接 Google（登入）』。")

    redirect_uri = get_redirect_uri()
    flow = build_google_oauth_flow(redirect_uri, code_verifier=verifier)
    flow.fetch_token(code=code)
    return flow.credentials


def credentials_to_dict(creds: Credentials) -> dict:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }


def credentials_from_dict(data: dict) -> Credentials:
    return Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes"),
    )
``

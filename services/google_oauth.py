import json
import streamlit as st
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials

# 建議 scopes：建立/修改 Google Forms + 在使用者 Drive 建立檔案
SCOPES = [
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/drive.file",
]


def oauth_is_configured() -> bool:
    """Streamlit secrets 內必須有 google_oauth_client。"""
    return "google_oauth_client" in st.secrets


def get_redirect_uri() -> str:
    """
    使用 Streamlit Secrets 的 APP_URL 作 redirect URI（部署後固定最穩）。
    Streamlit 建議用 secrets 管理敏感配置並用 st.secrets 讀取。[3](https://docs.ucloud.cn/modelverse/api_doc/text_api/deepseek-ocr?id=deepseek-ocr-%e6%a8%a1%e5%9e%8b)[4](blob:https://m365.cloud.microsoft/416c93ef-4252-48fd-a0d4-ad845993cab4)
    """
    app_url = str(st.secrets.get("APP_URL", "")).strip().rstrip("/")
    if app_url:
        return app_url
    return "http://localhost:8501"


def _load_google_client_config() -> dict:
    """
    Flow.from_client_config 需要 Google client secrets format，
    且 client type 只能是 web 或 installed。[1](https://cloud.google.com/use-cases/ocr)[2](https://zhuanlan.zhihu.com/p/1964739506629490036)
    """
    client = st.secrets["google_oauth_client"]

    # secrets 常用 """...""" 存 JSON 字串，先轉 dict
    if isinstance(client, str):
        client = json.loads(client)

    # 若只貼了 web 內部，幫你包回正確格式
    if "web" not in client and "installed" not in client:
        client = {"web": client}

    return client


def build_google_oauth_flow(redirect_uri: str) -> Flow:
    """
    建立 OAuth Flow（此版本：不使用 PKCE，避免 code_verifier 在 Streamlit session 切換時遺失）。
    """
    client_config = _load_google_client_config()
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    return flow


def get_or_create_auth_url() -> str:
    """
    只在第一次生成 auth_url/state，避免 rerun 覆蓋 state。
    """
    if st.session_state.get("google_oauth_auth_url") and st.session_state.get("google_oauth_state"):
        return st.session_state["google_oauth_auth_url"]

    redirect_uri = get_redirect_uri()
    flow = build_google_oauth_flow(redirect_uri)

    # 不使用 code_challenge_method（即不啟用 PKCE）
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    st.session_state["google_oauth_auth_url"] = auth_url
    st.session_state["google_oauth_state"] = state
    return auth_url


def clear_oauth_temp_state():
    """登入完成/失敗後清理暫存 state/url。"""
    for k in ("google_oauth_auth_url", "google_oauth_state"):
        st.session_state.pop(k, None)


def exchange_code_for_credentials(code: str, returned_state: str | None = None) -> Credentials:
    """
    用 callback 回來的 code 換取 Credentials。

    ✅ state 驗證策略（為 Streamlit Cloud 友善）：
    - 若本次 session 有 expected_state，就必須 match，否則報錯（防 CSRF）。
    - 若 expected_state 不存在（例如回跳開了新 session），就容錯接受 returned_state，
      但會建議用戶避免多分頁登入。
    """
    expected_state = st.session_state.get("google_oauth_state")

    if expected_state and returned_state and returned_state != expected_state:
        raise ValueError("state 不匹配：請重新按『連接 Google（登入）』。")

    redirect_uri = get_redirect_uri()
    flow = build_google_oauth_flow(redirect_uri)

    # 直接 fetch_token（無 PKCE）
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

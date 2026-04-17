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
    """
    Streamlit secrets 內必須有 google_oauth_client
    """
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

    # Streamlit secrets 常用做法：以 """...""" 存 JSON 字串，故這裡需 json.loads [3](https://docs.ucloud.cn/modelverse/api_doc/text_api/deepseek-ocr?id=deepseek-ocr-%e6%a8%a1%e5%9e%8b)[4](blob:https://m365.cloud.microsoft/416c93ef-4252-48fd-a0d4-ad845993cab4)
    if isinstance(client, str):
        client = json.loads(client)

    # 如果用戶只貼了 web 內部那段，幫佢包回正確格式
    if "web" not in client and "installed" not in client:
        client = {"web": client}

    return client


def build_google_oauth_flow(redirect_uri: str, code_verifier: str | None = None) -> Flow:
    """
    建立 OAuth Flow。
    重要：啟用 PKCE 時必須保存 code_verifier，否則會 invalid_grant Missing code verifier。[1](https://cloud.google.com/use-cases/ocr)
    """
    client_config = _load_google_client_config()

    # Flow 支援 code_verifier / autogenerate_code_verifier 參數（PKCE）[1](https://cloud.google.com/use-cases/ocr)
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
        autogenerate_code_verifier=(code_verifier is None),
    )
    return flow


def build_auth_url_and_store_pkce() -> str:
    """
    產生登入連結，並把 state + code_verifier 保存到 session_state。
    """
    redirect_uri = get_redirect_uri()
    flow = build_google_oauth_flow(redirect_uri)

    # 產生 auth_url，並使用 PKCE（S256）
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        code_challenge_method="S256",
    )

    # 保存 state 與 code_verifier（最關鍵）
    st.session_state["google_oauth_state"] = state
    st.session_state["google_oauth_code_verifier"] = flow.code_verifier

    return auth_url


def exchange_code_for_credentials(code: str, state: str | None = None) -> Credentials:
    """
    用 callback 回來的 code 換取 Credentials。
    會檢查 state 及使用之前保存的 code_verifier，避免 Missing code verifier。[1](https://cloud.google.com/use-cases/ocr)
    """
    expected_state = st.session_state.get("google_oauth_state")
    verifier = st.session_state.get("google_oauth_code_verifier")

    # state 檢查（防止 CSRF）
    if expected_state and state and state != expected_state:
        raise ValueError("state 不匹配：請重新按『連接 Google（登入）』。")

    if not verifier:
        raise ValueError("缺少 code_verifier：請重新按『連接 Google（登入）』。")

    redirect_uri = get_redirect_uri()
    flow = build_google_oauth_flow(redirect_uri, code_verifier=verifier)

    # fetch_token 會用 code_verifier 完成 PKCE 換 token [1](https://cloud.google.com/use-cases/ocr)
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

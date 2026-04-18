
import time
import secrets
import streamlit as st
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials

# 建立/修改 Google Forms + 在用戶 Drive 建立文件
SCOPES = [
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/drive.file",
]

# 用 state 作 key 暫存 flow（含 code_verifier 等資訊）
_OAUTH_FLOW_STORE = {}
_STORE_TTL_SEC = 15 * 60  # 15 分鐘


def _prune_store():
    now = time.time()
    expired = [k for k, v in _OAUTH_FLOW_STORE.items() if now - v.get("ts", 0) > _STORE_TTL_SEC]
    for k in expired:
        _OAUTH_FLOW_STORE.pop(k, None)


def oauth_is_configured() -> bool:
    """Streamlit secrets 內必須有 google_oauth_client。"""
    return "google_oauth_client" in st.secrets


def get_redirect_uri() -> str:
    """
    用 Streamlit Secrets 的 APP_URL 作 redirect URI（部署後固定最穩）。
    注意：redirect URI 必須與 Google Cloud Console 的 Authorized redirect URIs 完全一致。
    """
    app_url = str(st.secrets.get("APP_URL", "")).strip().rstrip("/")
    return app_url if app_url else "http://localhost:8501"


def _load_google_client_config() -> dict:
    """
    Flow.from_client_config 需要 Google client secrets format。
    secrets 內建議以 google_oauth_client 儲存整段 client JSON（web）。
    """
    return st.secrets["google_oauth_client"]


def get_auth_url() -> str:
    """
    生成登入 URL，並把 state -> flow 存入全域 store（跨 rerun 可取回）。
    Flow.authorization_url 會回傳 (auth_url, state)。[6](https://googleapis.dev/python/google-auth-oauthlib/latest/reference/google_auth_oauthlib.flow.html)
    """
    _prune_store()

    client_config = _load_google_client_config()
    redirect_uri = get_redirect_uri()

    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )

    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    _OAUTH_FLOW_STORE[state] = {"flow": flow, "ts": time.time()}
    return auth_url


def exchange_code_for_credentials(code: str, returned_state: str) -> Credentials:
    """
    用 callback 回來的 code 換取 Credentials（fetch_token）。[3](https://google-auth-oauthlib.readthedocs.io/en/latest/reference/google_auth_oauthlib.flow.html)[6](https://googleapis.dev/python/google-auth-oauthlib/latest/reference/google_auth_oauthlib.flow.html)
    會用 returned_state 從全域 store 找回 flow，避免 state 遺失。
    """
    _prune_store()

    if not returned_state:
        raise ValueError("Missing OAuth state.")
    entry = _OAUTH_FLOW_STORE.get(returned_state)
    if not entry:
        raise ValueError("OAuth state expired or not found. Please login again.")

    flow: Flow = entry["flow"]
    flow.fetch_token(code=code)

    creds = flow.credentials
    _OAUTH_FLOW_STORE.pop(returned_state, None)
    return creds


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

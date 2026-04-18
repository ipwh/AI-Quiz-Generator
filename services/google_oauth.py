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

# 全域暫存（以 state 作 key 保存 flow）；避免 callback 落到 rerun 後丟失資料
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
    若未設定，回退 localhost。
    """
    app_url = str(st.secrets.get("APP_URL", "")).strip().rstrip("/")
    return app_url if app_url else "http://localhost:8501"


def _load_google_client_config() -> dict:
    """
    Flow.from_client_config 需要 Google client secrets format。
    你的 secrets 應該存成 google_oauth_client。
    """
    return st.secrets["google_oauth_client"]


def _build_flow(redirect_uri: str) -> Flow:
    client_config = _load_google_client_config()
    return Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )


def get_auth_url() -> str:
    """生成登入 URL，並把 state -> flow 存入全域 store（跨 rerun 可取回）。"""
    _prune_store()

    state = secrets.token_urlsafe(24)
    flow = _build_flow(get_redirect_uri())

    auth_url, returned_state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )

    _OAUTH_FLOW_STORE[returned_state] = {"flow": flow, "ts": time.time()}
    return auth_url


def exchange_code_for_credentials(code: str, returned_state: str) -> Credentials:
    """
    用 callback 回來的 code 換取 Credentials。
    會用 returned_state 從全域 store 找回 flow，避免 Missing verifier/state mismatch。
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

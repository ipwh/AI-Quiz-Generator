import json
import time
import secrets
import streamlit as st
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/drive.file",
]

_OAUTH_FLOW_STORE = {}
_STORE_TTL_SEC = 15 * 60  # 15 分鐘


def _prune_store():
    now = time.time()
    expired = [k for k, v in _OAUTH_FLOW_STORE.items() if now - v.get("ts", 0) > _STORE_TTL_SEC]
    for k in expired:
        _OAUTH_FLOW_STORE.pop(k, None)


def oauth_is_configured() -> bool:
    return "google_oauth_client" in st.secrets


def get_redirect_uri() -> str:
    app_url = str(st.secrets.get("APP_URL", "")).strip().rstrip("/")
    return app_url if app_url else "http://localhost:8501"


def _load_google_client_config() -> dict:
    """
    st.secrets["google_oauth_client"] 可能係：
    1) dict-like（TOML mapping）✅
    2) JSON 字串（用 """{...}""" 貼入 secrets）➡️ 需要 json.loads ✅
    """
    raw = st.secrets["google_oauth_client"]

    # 方案 1：已經係 mapping
    if isinstance(raw, dict):
        return raw

    # 方案 2：Streamlit secrets 可能回傳 AttributeDict / 類 dict
    try:
        # 有些情況 raw 係可轉 dict
        return dict(raw)
    except Exception:
        pass

    # 方案 3：raw 係 JSON string
    if isinstance(raw, str):
        raw_s = raw.strip()
        try:
            return json.loads(raw_s)
        except Exception as e:
            raise ValueError(
                "google_oauth_client 似乎係字串，但唔係有效 JSON。"
                "建議用 TOML mapping 方式儲存（[google_oauth_client][google_oauth_client.web]...）"
            ) from e

    raise ValueError("google_oauth_client 格式不正確，必須係 dict 或 JSON 字串。")


def get_auth_url() -> str:
    """
    產生 Google OAuth 登入 URL，並暫存 flow（用 state 作 key）。
    Flow.authorization_url / fetch_token 係標準用法。[1](https://pccss-my.sharepoint.com/personal/ipwh_ms_pochiu_edu_hk).csv&action=default&mobileredirect=true)
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
    _prune_store()

    if not returned_state:
        raise ValueError("Missing OAuth state.")
    entry = _OAUTH_FLOW_STORE.get(returned_state)
    if not entry:
        raise ValueError("OAuth state expired or not found. Please login again.")

    flow: Flow = entry["flow"]
    flow.fetch_token(code=code)  # 標準做法[1](https://pccss-my.sharepoint.com/personal/ipwh_ms_pochiu_edu_hk).csv&action=default&mobileredirect=true)

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

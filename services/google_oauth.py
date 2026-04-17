import json
import time
import secrets
import streamlit as st
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials

# 需要的 scopes：建立/修改 Google Forms + 在用戶 Drive 建立文件
SCOPES = [
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/drive.file",
]

# ✅ 全域暫存：用 state 作 key 保存 code_verifier
# 目的：避免 Streamlit Cloud callback 落到另一個 session 而丟失 verifier
_OAUTH_STORE: dict[str, dict] = {}
_STORE_TTL_SEC = 15 * 60  # 15 分鐘自動過期


def oauth_is_configured() -> bool:
    """Streamlit secrets 內必須有 google_oauth_client。"""
    return "google_oauth_client" in st.secrets


def get_redirect_uri() -> str:
    """
    用 Streamlit Secrets 的 APP_URL 作 redirect URI（部署後固定最穩）。
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

    # 常見做法：在 Secrets 用 """...""" 存 JSON 字串，需先 json.loads 轉 dict
    if isinstance(client, str):
        client = json.loads(client)

    # 若只貼 web 內部那段，幫你包回正確格式
    if "web" not in client and "installed" not in client:
        client = {"web": client}

    return client


def _prune_store():
    """清理過期的 state 記錄"""
    now = time.time()
    expired = [k for k, v in _OAUTH_STORE.items() if now - v.get("ts", 0) > _STORE_TTL_SEC]
    for k in expired:
        _OAUTH_STORE.pop(k, None)


def build_google_oauth_flow(redirect_uri: str, code_verifier: str | None = None) -> Flow:
    """
    建立 OAuth Flow（包含 PKCE 支援）。
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


def get_auth_url() -> str:
    """
    生成登入 URL，並把 state -> code_verifier 存入全域 store（跨 session 可取回）。
    """
    _prune_store()

    redirect_uri = get_redirect_uri()
    flow = build_google_oauth_flow(redirect_uri)

    # 這個 state 我們自行生成，確保可控、可查
    state = secrets.token_urlsafe(24)

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
        code_challenge_method="S256",
    )

    # 保存 verifier 供 callback 換 token 使用
    _OAUTH_STORE[state] = {"verifier": flow.code_verifier, "ts": time.time()}

    return auth_url


def exchange_code_for_credentials(code: str, returned_state: str | None) -> Credentials:
    """
    用 callback 回來的 code 換取 Credentials。
    會用 returned_state 從全域 store 找回 code_verifier，避免 Missing code verifier。
    """
    _prune_store()

    if not returned_state:
        raise ValueError("缺少 state（請重新按『連接 Google（登入）』）。")

    record = _OAUTH_STORE.get(returned_state)
    if not record:
        raise ValueError("state 已過期或不存在（請重新按『連接 Google（登入）』，並避免多分頁）。")

    verifier = record.get("verifier")
    if not verifier:
        raise ValueError("缺少 code_verifier（請重新按『連接 Google（登入）』）。")

    redirect_uri = get_redirect_uri()
    flow = build_google_oauth_flow(redirect_uri, code_verifier=verifier)

    # 用 code + verifier 換 token（PKCE）
    flow.fetch_token(code=code)

    # 換完就刪除，避免重放
    _OAUTH_STORE.pop(returned_state, None)

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

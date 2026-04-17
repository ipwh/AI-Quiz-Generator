import json
import os
from urllib.parse import urlparse

import streamlit as st
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials

SCOPES = [
    'https://www.googleapis.com/auth/forms.body',
    'https://www.googleapis.com/auth/drive.file'
]


def oauth_is_configured() -> bool:
    return 'google_oauth_client' in st.secrets


def get_redirect_uri() -> str:
    """使用目前 app 的 URL 作 redirect URI。

    Streamlit Cloud: https://<app>.streamlit.app
    Local: http://localhost:8501
    """
    # Streamlit 提供 server.baseUrlPath 但未必包含 domain。
    # 用 query param 回傳需要完整 URI。
    # 簡化：讓使用者在 Secrets 設定 APP_URL（部署後固定）
    app_url = st.secrets.get('APP_URL', '').rstrip('/')
    if app_url:
        return app_url
    # fallback：本機
    return 'http://localhost:8501'


def build_google_oauth_flow(redirect_uri: str) -> Flow:
    client = st.secrets['google_oauth_client']
    flow = Flow.from_client_config(client, scopes=SCOPES, redirect_uri=redirect_uri)
    return flow


def exchange_code_for_credentials(redirect_uri: str, code: str) -> Credentials:
    flow = build_google_oauth_flow(redirect_uri)
    flow.fetch_token(code=code)
    return flow.credentials


def credentials_to_dict(creds: Credentials) -> dict:
    return {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': creds.scopes,
    }


def credentials_from_dict(data: dict) -> Credentials:
    return Credentials(
        token=data.get('token'),
        refresh_token=data.get('refresh_token'),
        token_uri=data.get('token_uri'),
        client_id=data.get('client_id'),
        client_secret=data.get('client_secret'),
        scopes=data.get('scopes'),
    )

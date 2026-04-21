import io
import re
import requests
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SUPPORTED_MIME_EXPORT = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "pptx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsx",
    ),
}

SUPPORTED_DIRECT_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
    "image/png",
    "image/jpeg",
}


def _drive_service(creds):
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def extract_file_id(link_or_id: str) -> str:
    """從分享連結或純 ID 抽出 file_id。"""
    s = link_or_id.strip()
    # 嘗試從 URL 抽取
    patterns = [
        r"/file/d/([a-zA-Z0-9_-]+)",
        r"id=([a-zA-Z0-9_-]+)",
        r"open\?id=([a-zA-Z0-9_-]+)",
    ]
    for p in patterns:
        m = re.search(p, s)
        if m:
            return m.group(1)
    # 若無 URL 特徵，直接當 ID 用
    if re.match(r"^[a-zA-Z0-9_-]{10,}$", s):
        return s
    raise ValueError(f"無法辨識 Drive 連結或 ID：{s}")


def get_file_meta(creds, file_id: str) -> dict:
    """取得檔案 metadata（name, mimeType, size）。"""
    service = _drive_service(creds)
    return service.files().get(
        fileId=file_id,
        fields="id, name, mimeType, size"
    ).execute()


def download_file(creds, file_id: str) -> tuple[bytes, str, str]:
    """
    下載檔案，回傳 (bytes, filename, ext)。
    Google Docs/Slides/Sheets 自動 export 為 Office 格式。
    """
    service = _drive_service(creds)
    meta = get_file_meta(creds, file_id)
    mime = meta.get("mimeType", "")
    name = meta.get("name", "file")

    # Google Workspace 格式 → export
    if mime in SUPPORTED_MIME_EXPORT:
        export_mime, ext = SUPPORTED_MIME_EXPORT[mime]
        data = service.files().export_media(
            fileId=file_id, mimeType=export_mime
        ).execute()
        return data, f"{name}.{ext}", ext

    # 一般二進位格式 → 直接下載
    if mime in SUPPORTED_DIRECT_MIME or True:
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, service.files().get_media(fileId=file_id))
        done = False
        while not done:
            _, done = dl.next_chunk()
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else "bin"
        return buf.getvalue(), name, ext

    raise ValueError(f"不支援的檔案格式：{mime}")


def list_recent_files(creds, max_results: int = 30) -> list[dict]:
    """
    列出用戶 Drive 最近修改的教材類檔案。
    回傳 [{"id", "name", "mimeType", "modifiedTime"}, ...]
    """
    service = _drive_service(creds)
    mime_filters = " or ".join([
        f"mimeType='{m}'" for m in list(SUPPORTED_MIME_EXPORT.keys()) + [
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "text/plain",
            "image/png",
            "image/jpeg",
        ]
    ])
    query = f"trashed=false and ({mime_filters})"
    result = service.files().list(
        q=query,
        pageSize=max_results,
        orderBy="modifiedTime desc",
        fields="files(id, name, mimeType, modifiedTime)",
    ).execute()
    return result.get("files", [])

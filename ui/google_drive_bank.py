import io
import json
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

BANK_MIME = "application/json"


def _drive(creds):
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def create_bank_file(creds, name: str = "AI Quiz Bank.json") -> str:
    """
    建立一個 Drive JSON 檔案作題庫，回傳 fileId。
    """
    service = _drive(creds)
    metadata = {"name": name, "mimeType": BANK_MIME}
    # 初始內容：空陣列
    media = MediaIoBaseUpload(io.BytesIO(b"[]"), mimetype=BANK_MIME, resumable=False)
    f = service.files().create(body=metadata, media_body=media, fields="id").execute()
    return f["id"]


def load_bank(creds, file_id: str):
    """
    下載題庫 JSON，回傳 list。
    """
    service = _drive(creds)
    data = service.files().get_media(fileId=file_id).execute()
    try:
        items = json.loads(data.decode("utf-8"))
        return items if isinstance(items, list) else []
    except Exception:
        return []


def save_bank(creds, file_id: str, items: list):
    """
    上載題庫 JSON（覆蓋更新）。
    """
    service = _drive(creds)
    payload = json.dumps(items, ensure_ascii=False, indent=2).encode("utf-8")
    media = MediaIoBaseUpload(io.BytesIO(payload), mimetype=BANK_MIME, resumable=False)
    service.files().update(fileId=file_id, media_body=media).execute()


def append_questions(creds, file_id: str, questions: list, subject: str = "") -> int:
    """
    把 questions（list[dict]）加入題庫，回傳新增數量。
    """
    bank = load_bank(creds, file_id)
    now = datetime.utcnow().isoformat() + "Z"

    added = 0
    for q in questions:
        if not isinstance(q, dict):
            continue
        item = dict(q)
        item["subject"] = item.get("subject") or subject
        item["created_at"] = item.get("created_at") or now
        bank.append(item)
        added += 1

    save_bank(creds, file_id, bank)
    return added


def share_bank_with_emails(creds, file_id: str, emails: list, role: str = "writer"):
    """
    以電郵分享題庫（Drive permission + sendNotificationEmail）。
    role: writer / reader
    """
    service = _drive(creds)
    for email in emails:
        email = str(email).strip()
        if not email:
            continue
        body = {"type": "user", "role": role, "emailAddress": email}
        service.permissions().create(
            fileId=file_id,
            body=body,
            sendNotificationEmail=True,
        ).execute()
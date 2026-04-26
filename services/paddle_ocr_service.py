# services/paddle_ocr_service.py
from __future__ import annotations
import io
from typing import Optional
from PIL import Image

PADDLE_AVAILABLE = False
try:
    from paddleocr import PaddleOCR
    PADDLE_AVAILABLE = True
except Exception:
    PADDLE_AVAILABLE = False


def create_ocr(lang: str = "ch") -> Optional["PaddleOCR"]:
    """
    建立 PaddleOCR instance（延遲載入）
    lang="ch": 通用中文（推薦：穩定、支援簡繁）
    """
    if not PADDLE_AVAILABLE:
        return None

    # use_angle_cls=True：對掃描/拍照歪斜更穩
    return PaddleOCR(
        use_angle_cls=True,
        lang=lang,
        show_log=False,
    )


def ocr_image_bytes(ocr: "PaddleOCR", image_bytes: bytes) -> str:
    """
    將 image bytes 交畀 PaddleOCR，回傳純文字
    """
    if ocr is None:
        return ""

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return ""

    result = ocr.ocr(img, cls=True)
    if not result:
        return ""

    lines = []
    for line in result:
        # line: [box, (text, score)]
        if not line or len(line) < 2:
            continue
        text = line[1][0] if line[1] else ""
        if text and text.strip():
            lines.append(text.strip())

    return "\n".join(lines).strip()

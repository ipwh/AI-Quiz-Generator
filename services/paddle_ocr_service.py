# paddle_ocr_service.py
import io
import threading
import numpy as np
from PIL import Image

try:
    from paddleocr import PaddleOCR
    PADDLE_AVAILABLE = True
except Exception as e:
    print("Paddle import failed:", e)
    PADDLE_AVAILABLE = False


__OCR_INSTANCE = None
__LOCK = threading.Lock()


def is_available() -> bool:
    return PADDLE_AVAILABLE


def get_ocr():
    global __OCR_INSTANCE

    if not PADDLE_AVAILABLE:
        return None

    if __OCR_INSTANCE is None:
        with __LOCK:
            if __OCR_INSTANCE is None:
                __OCR_INSTANCE = PaddleOCR(
                    use_angle_cls=True,
                    lang="ch",
                    show_log=True,   # ← 暫時開 log，非常重要
                )
    return __OCR_INSTANCE


def ocr_image_bytes(image_bytes: bytes) -> str:
    ocr = get_ocr()
    if ocr is None:
        print("OCR not available")
        return ""

    try:
        pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img = np.array(pil_img)   # ✅ 關鍵
    except Exception as e:
        print("Image decode failed:", e)
        return ""

    try:
        result = ocr.ocr(img, cls=True)
        print("OCR raw result:", result)
    except Exception as e:
        print("OCR runtime error:", e)
        return ""

    texts = []
    for page in result or []:
        for line in page:
            if line and len(line) > 1:
                texts.append(line[1][0])

    return "\n".join(texts).strip()

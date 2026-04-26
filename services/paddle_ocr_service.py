# paddle_ocr_service.py
import io
import threading
from PIL import Image

try:
    from paddleocr import PaddleOCR
    PADDLE_AVAILABLE = True
except Exception:
    PADDLE_AVAILABLE = False


__OCR_INSTANCE = None
__LOCK = threading.Lock()


def is_available() -> bool:
    return PADDLE_AVAILABLE


def get_ocr():
    """
    Lazily initialize a singleton PaddleOCR instance.
    Safe for Streamlit / multi-call usage.
    """
    global __OCR_INSTANCE

    if not PADDLE_AVAILABLE:
        return None

    if __OCR_INSTANCE is None:
        with __LOCK:
            if __OCR_INSTANCE is None:
                __OCR_INSTANCE = PaddleOCR(
                    use_angle_cls=True,
                    lang="ch",      # 中英混合，如只英文可改 "en"
                    show_log=False,
                )
    return __OCR_INSTANCE


def ocr_image_bytes(image_bytes: bytes) -> str:
    """
    Perform OCR on image bytes and return plain text.
    """
    ocr = get_ocr()
    if ocr is None:
        return ""

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return ""

    try:
        result = ocr.ocr(img, cls=True)
    except Exception:
        return ""

    texts = []
    for page in result:
        for line in page:
            texts.append(line[1][0])

    return "\n".join(texts).strip()

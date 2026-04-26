# paddle_ocr_service.py
import io
import threading
import numpy as np
from PIL import Image

# ---------- PaddleOCR ----------
try:
    from paddleocr import PaddleOCR
    PADDLE_AVAILABLE = True
except Exception as e:
    print("[OCR] Paddle import failed:", e)
    PADDLE_AVAILABLE = False

# ---------- Tesseract ----------
try:
    import pytesseract
    TESS_AVAILABLE = True
except Exception as e:
    print("[OCR] Tesseract import failed:", e)
    TESS_AVAILABLE = False


__OCR_INSTANCE = None
__LOCK = threading.Lock()


def get_paddle_ocr():
    global __OCR_INSTANCE
    if not PADDLE_AVAILABLE:
        return None

    if __OCR_INSTANCE is None:
        with __LOCK:
            if __OCR_INSTANCE is None:
                __OCR_INSTANCE = PaddleOCR(
                    use_angle_cls=True,
                    lang="ch",
                    use_gpu=False,
                    show_log=False,
                )
    return __OCR_INSTANCE


def _ocr_with_paddle(image: Image.Image) -> str:
    ocr = get_paddle_ocr()
    if ocr is None:
        return ""

    try:
        img = np.array(image)
        result = ocr.ocr(img, cls=True)
    except Exception:
        return ""

    texts = []
    for page in result or []:
        for line in page:
            texts.append(line[1][0])

    return "\n".join(texts).strip()


def _ocr_with_tesseract(image: Image.Image) -> str:
    if not TESS_AVAILABLE:
        return ""

    try:
        return pytesseract.image_to_string(
            image,
            lang="chi_tra+chi_sim+eng",
        ).strip()
    except Exception:
        return ""


def ocr_image_bytes(image_bytes: bytes) -> str:
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return ""

    # 1️⃣ PaddleOCR first
    text = _ocr_with_paddle(image)
    if text:
        return text

    # 2️⃣ Fallback to Tesseract (✅ 一定穩)
    return _ocr_with_tesseract(image)

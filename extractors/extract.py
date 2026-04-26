# extractors/extract.py
# P0：統一 data URL helper
# P2：OCR 閾值調低，加入理科符號
# P3：PaddleOCR 主力（繁體中文手寫）> Tesseract 備援

import io
import re
import base64
import fitz
import docx
import openpyxl
from pptx import Presentation

# ── Tesseract（備援）─────────────────────────────
try:
    import pytesseract
    from PIL import Image, ImageOps
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False
    Image = None
    ImageOps = None

# ── PaddleOCR（主力，延遲初始化）────────────────
_paddle_ocr = None
PADDLEOCR_AVAILABLE = False
_PADDLE_IMPORT_ERROR = ""  # ← 新增

try:
    from paddleocr import PaddleOCR as _PaddleOCR
    PADDLEOCR_AVAILABLE = True
except Exception as e:
    _PaddleOCR = None
    _PADDLE_IMPORT_ERROR = str(e)  # ← 記錄錯誤

def _get_paddle_reader():
    global _paddle_ocr
    if _paddle_ocr is None and PADDLEOCR_AVAILABLE:
        try:
            import os
            # 指定模型下載至可寫目錄
            os.environ.setdefault("PADDLEOCR_HOME", "/tmp/.paddleocr")
            _paddle_ocr = _PaddleOCR(
                use_angle_cls=True,
                lang="chinese_cht",
                use_gpu=False,
                show_log=True,   # ← 改為 True，讓 Cloud logs 顯示載入狀態
                ocr_version="PP-OCRv4",
            )
        except Exception:
            import traceback
            traceback.print_exc()
            _paddle_ocr = None
    return _paddle_ocr


_HAS_PYMUPDF = True

# =========================================================
# data URL helper
# =========================================================

def bytes_to_data_url(b: bytes, mime: str) -> str:
    if not mime:
        mime = "application/octet-stream"
    b64 = base64.b64encode(b).decode("utf-8")
    return f"data:{mime};base64,{b64}"


# =========================================================
# Text helpers
# =========================================================

def _clean_text(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


_READABLE_PATTERN = re.compile(
    r"[A-Za-z0-9\u4e00-\u9fff"
    r"°μΩαβγδεζθλπσφψω"
    r"\+\-×÷=<>≤≥≠±√∑∞∫∂∇"
    r"→←↑↓⇌°℃℉\(\)\[\]{}|/\\^_~`]"
)

_GARBAGE_PATTERN = re.compile(
    r"[^\x09\x0a\x0d\x20-\x7e\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]{4,}"
)


def _text_quality_score(s: str) -> float:
    if not s:
        return 0.0
    return len(_READABLE_PATTERN.findall(s)) / max(len(s), 1)


def _is_garbage_text(s: str) -> bool:
    if not s:
        return True
    gc = sum(len(m) for m in _GARBAGE_PATTERN.findall(s))
    return (gc / max(len(s), 1)) > 0.40


# =========================================================
# File extractors
# =========================================================

def _extract_pdf_text(data: bytes) -> str:
    parts = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            parts.append(page.get_text())
    return _clean_text("\n".join(parts))


def _extract_docx_text(data: bytes) -> str:
    document = docx.Document(io.BytesIO(data))
    return _clean_text("\n".join(p.text for p in document.paragraphs if p.text))


def _extract_txt_text(data: bytes) -> str:
    try:
        return _clean_text(data.decode("utf-8"))
    except Exception:
        return _clean_text(data.decode("utf-8", errors="ignore"))


def _extract_xlsx_text(data: bytes) -> str:
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    chunks = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            for cell in row:
                if cell is not None:
                    s = str(cell).strip()
                    if s:
                        chunks.append(s)
    return _clean_text("\n".join(chunks))


def _extract_pptx_text(data: bytes) -> str:
    prs = Presentation(io.BytesIO(data))
    chunks = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if hasattr(shape, "text"):
                s = str(shape.text).strip()
                if s:
                    chunks.append(s)
    return _clean_text("\n".join(chunks))


# =========================================================
# OCR helpers
# =========================================================

def _ocr_paddle(image_bytes: bytes) -> str:
    reader = _get_paddle_reader()
    if reader is None:
        return ""
    try:
        import numpy as np
        from PIL import Image as PILImage
        img = PILImage.open(io.BytesIO(image_bytes)).convert("RGB")
        arr = np.array(img)
        result = reader.ocr(arr, cls=True)
        lines = []
        for block in (result or []):
            for item in (block or []):
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    text_info = item[1]
                    if isinstance(text_info, (list, tuple)) and len(text_info) >= 1:
                        t = str(text_info[0])
                        conf = float(text_info[1]) if len(text_info) >= 2 else 0.0
                        # ✅ 新增：只保留信心值 > 0.5 的結果
                        if conf > 0.5:
                            lines.append(t)
        text = _clean_text("\n".join(lines))
        return "" if _is_garbage_text(text) else text
    except Exception as e:
        # 部署時可在 Streamlit logs 看到此錯誤
        import traceback
        traceback.print_exc()
        return ""


def _ocr_tesseract(image_bytes: bytes, lang: str = "chi_tra+chi_sim+eng") -> str:
    """備援 OCR：Tesseract。"""
    if not OCR_AVAILABLE:
        return ""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("L")
        img = ImageOps.autocontrast(img)
        text = _clean_text(pytesseract.image_to_string(img, lang=lang))
        if _text_quality_score(text) < 0.15 or _is_garbage_text(text):
            return ""
        return text
    except Exception:
        return ""


def _ocr_image_bytes(image_bytes: bytes, lang: str = "chi_tra+chi_sim+eng") -> str:
    """統一 OCR 入口：PaddleOCR 優先 → Tesseract 備援。"""
    if PADDLEOCR_AVAILABLE:
        result = _ocr_paddle(image_bytes)
        if result:
            return result
    return _ocr_tesseract(image_bytes, lang=lang)


# =========================================================
# Vision helpers
# =========================================================

def _pdf_pages_to_images_data_url(data: bytes, max_pages: int = 3, zoom: float = 2.0):
    imgs = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        mat = fitz.Matrix(zoom, zoom)
        for i in range(min(len(doc), max_pages)):
            pix = doc[i].get_pixmap(matrix=mat, alpha=False)
            imgs.append(bytes_to_data_url(pix.tobytes("png"), "image/png"))
    return imgs


# =========================================================
# Main: extract_payload
# =========================================================

def extract_payload(
    file,
    enable_ocr: bool = False,
    ocr_lang: str = "chi_tra+chi_sim+eng",
    enable_vision: bool = False,
    vision_pdf_max_pages: int = 3,
) -> dict:
    ext = file.name.split(".")[-1].lower()
    data = file.getvalue()
    out = {"text": "", "images": [], "meta": {"ext": ext}}
    try:
        if ext == "pdf":
            text = _extract_pdf_text(data)
            out["text"] = text
            if len(text) < 50:
                if enable_ocr:
                    parts = []
                    with fitz.open(stream=data, filetype="pdf") as doc:
                        mat = fitz.Matrix(2.5, 2.5)
                        for i in range(len(doc)):
                            pix = doc[i].get_pixmap(matrix=mat, alpha=False)
                            t = _ocr_image_bytes(pix.tobytes("png"), lang=ocr_lang)
                            if t:
                                parts.append(t)
                    out["text"] = _clean_text("\n".join(parts))
                if enable_vision:
                    try:
                        out["images"] = _pdf_pages_to_images_data_url(
                            data, max_pages=vision_pdf_max_pages, zoom=2.0
                        )
                    except Exception:
                        out["images"] = []
            return out

        if ext == "docx":
            out["text"] = _extract_docx_text(data); return out
        if ext == "txt":
            out["text"] = _extract_txt_text(data); return out
        if ext == "xlsx":
            out["text"] = _extract_xlsx_text(data); return out
        if ext == "pptx":
            out["text"] = _extract_pptx_text(data); return out

        if ext in {"png", "jpg", "jpeg"}:
            mime = "image/png" if ext == "png" else "image/jpeg"
            if enable_ocr:
                out["text"] = _ocr_image_bytes(data, lang=ocr_lang)
            if enable_vision:
                out["images"] = [bytes_to_data_url(data, mime)]
            return out

    except Exception:
        pass
    return out


# =========================================================
# extract_images_for_llm_ocr
# =========================================================

def extract_images_for_llm_ocr(file, pdf_max_pages: int = 3, pdf_zoom: float = 2.0):
    name = getattr(file, "name", "")
    ext = name.split(".")[-1].lower()
    data = file.getvalue()
    if ext in {"png", "jpg", "jpeg"}:
        mime = "image/png" if ext == "png" else "image/jpeg"
        return [bytes_to_data_url(data, mime)]
    if ext == "pdf":
        return _pdf_pages_to_images_data_url(
            data, max_pages=max(1, int(pdf_max_pages)), zoom=float(pdf_zoom)
        )
    return []


# =========================================================
# 兼容舊接口
# =========================================================

def extract_text(file, enable_ocr: bool = False,
                 ocr_lang: str = "chi_tra+chi_sim+eng") -> str:
    return extract_payload(
        file, enable_ocr=enable_ocr, ocr_lang=ocr_lang, enable_vision=False
    ).get("text", "")


_image_bytes_to_data_url = bytes_to_data_url
_bytes_to_data_url = bytes_to_data_url


def get_ocr_status() -> dict:
    """回傳 OCR 可用狀態，供 sidebar 顯示。"""
    return {
        "paddleocr": PADDLEOCR_AVAILABLE,
        "tesseract": OCR_AVAILABLE,
        "paddle_error": _PADDLE_IMPORT_ERROR,  # ← 新增
    }

# extractors/extract.py
# ---------------------------------------------------------
# P0：統一唯一 data URL helper（bytes_to_data_url）
# P1：移除底部重複 import / 重複實作，extract_images_for_llm_ocr 改呼叫共用 helper
# P2：OCR 品質閾值調低至 0.15，可讀字符集加入理科常用符號
# ---------------------------------------------------------

import io
import re
import base64
import fitz  # PyMuPDF
import docx
import openpyxl
from pptx import Presentation

# OCR (optional)
try:
    import pytesseract
    from PIL import Image, ImageOps
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

try:
    _HAS_PYMUPDF = True  # fitz already imported above
except Exception:
    _HAS_PYMUPDF = False

# =========================================================
# P0：唯一 data URL helper（全檔案統一使用此函數）
# =========================================================

def bytes_to_data_url(b: bytes, mime: str) -> str:
    """
    回傳標準 data URL：data:{mime};base64,{b64}
    確保 mime 非空；若為空則 fallback 至 application/octet-stream。
    """
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


# P2：擴充可讀字符集，加入理科常見符號
_READABLE_PATTERN = re.compile(
    r"[A-Za-z0-9\u4e00-\u9fff"
    r"°μΩαβγδεζθλπσφψω"   # 希臘字母
    r"\+\-×÷=<>≤≥≠±√∑∞∫∂∇"  # 數學符號
    r"→←↑↓⇌"              # 化學/物理箭頭
    r"°℃℉"                 # 溫度單位
    r"\(\)\[\]{}|/\\^_~`"  # 括號及常見符號
    r"]"
)

def _text_quality_score(s: str) -> float:
    """
    P2：可讀字符比例（中英數 + 理科符號）/ 總長度
    閾值由 0.25 降至 0.15
    """
    if not s:
        return 0.0
    good = len(_READABLE_PATTERN.findall(s))
    return good / max(len(s), 1)

# P2：改為「連續亂碼比例 > 40%」判斷，而非單純閾值
_GARBAGE_PATTERN = re.compile(r"[^\x09\x0a\x0d\x20-\x7e\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]{4,}")

def _is_garbage_text(s: str) -> bool:
    """True = OCR 結果太多亂碼，應丟棄。"""
    if not s:
        return True
    garbage_chars = sum(len(m) for m in _GARBAGE_PATTERN.findall(s))
    return (garbage_chars / max(len(s), 1)) > 0.40


# =========================================================
# File text extractors
# =========================================================

def _extract_pdf_text(data: bytes) -> str:
    parts = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            parts.append(page.get_text())
    return _clean_text("\n".join(parts))


def _extract_docx_text(data: bytes) -> str:
    document = docx.Document(io.BytesIO(data))
    text = "\n".join(p.text for p in document.paragraphs if p.text)
    return _clean_text(text)


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
                if cell is None:
                    continue
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

def _preprocess_image_for_ocr(img: "Image.Image") -> "Image.Image":
    img = img.convert("L")
    img = ImageOps.autocontrast(img)
    return img


def _ocr_image_bytes(image_bytes: bytes, lang: str = "chi_tra+chi_sim+eng") -> str:
    if not OCR_AVAILABLE:
        return ""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = _preprocess_image_for_ocr(img)
        text = pytesseract.image_to_string(img, lang=lang)
        text = _clean_text(text)
        # P2：用雙重條件過濾：閾值 0.15 + 亂碼比例 < 40%
        if _text_quality_score(text) < 0.15 or _is_garbage_text(text):
            return ""
        return text
    except Exception:
        return ""


# =========================================================
# Vision / data URL helpers（全部使用 bytes_to_data_url）
# =========================================================

def _pdf_pages_to_images_data_url(data: bytes, max_pages: int = 3, zoom: float = 2.0):
    """Vision 用：PDF 前 max_pages 頁渲染成 PNG data URL。"""
    imgs = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        n = min(len(doc), max_pages)
        mat = fitz.Matrix(zoom, zoom)
        for i in range(n):
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
    """
    回傳：{ "text": str, "images": [data_url,...], "meta": {...} }
    """
    ext = file.name.split(".")[-1].lower()
    data = file.getvalue()
    out = {"text": "", "images": [], "meta": {"ext": ext}}

    try:
        if ext == "pdf":
            text = _extract_pdf_text(data)
            out["text"] = text

            # 掃描 PDF：抽字太少 → OCR / Vision
            if len(text) < 50:
                if enable_ocr and OCR_AVAILABLE:
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
            out["text"] = _extract_docx_text(data)
            return out
        if ext == "txt":
            out["text"] = _extract_txt_text(data)
            return out
        if ext == "xlsx":
            out["text"] = _extract_xlsx_text(data)
            return out
        if ext == "pptx":
            out["text"] = _extract_pptx_text(data)
            return out

        # Image input
        if ext in {"png", "jpg", "jpeg"}:
            mime = "image/png" if ext == "png" else "image/jpeg"
            if enable_ocr:
                out["text"] = _ocr_image_bytes(data, lang=ocr_lang)
            if enable_vision:
                out["images"] = [bytes_to_data_url(data, mime)]
            return out

        return out

    except Exception:
        return out


# =========================================================
# P1：extract_images_for_llm_ocr 改呼叫共用 bytes_to_data_url
# =========================================================

def extract_images_for_llm_ocr(file, pdf_max_pages: int = 3, pdf_zoom: float = 2.0):
    """
    將圖片 / 掃描PDF（前N頁）轉成 data URL 供多模態 LLM 讀圖用。
    統一使用 bytes_to_data_url()，不再重複實作。
    """
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

def extract_text(
    file,
    enable_ocr: bool = False,
    ocr_lang: str = "chi_tra+chi_sim+eng",
) -> str:
    return extract_payload(
        file, enable_ocr=enable_ocr, ocr_lang=ocr_lang, enable_vision=False
    ).get("text", "")


# 兼容舊名稱
_image_bytes_to_data_url = bytes_to_data_url
_bytes_to_data_url = bytes_to_data_url

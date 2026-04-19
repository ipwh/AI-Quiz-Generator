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


def _clean_text(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _text_quality_score(s: str) -> float:
    """
    粗略 OCR 品質分數：可讀字符比例（中英數）/總長度
    """
    if not s:
        return 0.0
    total = len(s)
    good = len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", s))
    return good / max(total, 1)


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


def _preprocess_image_for_ocr(img: Image.Image) -> Image.Image:
    # 灰階 + 自動對比（保守處理）
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
        # 品質過低就回傳空，避免垃圾 OCR 影響出題
        if _text_quality_score(text) < 0.25:
            return ""
        return text
    except Exception:
        return ""


def _image_bytes_to_data_url(image_bytes: bytes, mime: str) -> str:
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _pdf_pages_to_images_data_url(data: bytes, max_pages: int = 3, zoom: float = 2.0):
    """
    Vision fallback 用：只取前 max_pages 頁（避免成本/超時）
    """
    imgs = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        n = min(len(doc), max_pages)
        mat = fitz.Matrix(zoom, zoom)
        for i in range(n):
            pix = doc[i].get_pixmap(matrix=mat, alpha=False)
            img_bytes = pix.tobytes("png")
            imgs.append(_image_bytes_to_data_url(img_bytes, "image/png"))
    return imgs


def extract_payload(
    file,
    enable_ocr: bool = False,
    ocr_lang: str = "chi_tra+chi_sim+eng",
    enable_vision: bool = False,
    vision_pdf_max_pages: int = 3,
) -> dict:
    """
    回傳：
      { "text": str, "images": [data_url,...], "meta": {...} }
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
                if enable_ocr:
                    if OCR_AVAILABLE:
                        parts = []
                        with fitz.open(stream=data, filetype="pdf") as doc:
                            mat = fitz.Matrix(2.5, 2.5)  # OCR 更清晰
                            for i in range(len(doc)):     # OCR 不限制頁數（依你要求）
                                pix = doc[i].get_pixmap(matrix=mat, alpha=False)
                                t = _ocr_image_bytes(pix.tobytes("png"), lang=ocr_lang)
                                if t:
                                    parts.append(t)
                        out["text"] = _clean_text("\n".join(parts))
                    else:
                        out["text"] = ""

                if enable_vision:
                    try:
                        out["images"] = _pdf_pages_to_images_data_url(data, max_pages=vision_pdf_max_pages, zoom=2.0)
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
                out["images"] = [_image_bytes_to_data_url(data, mime)]
            return out

        return out

    except Exception:
        return out


# 兼容舊接口：只回傳文字
def extract_text(file, enable_ocr: bool = False, ocr_lang: str = "chi_tra+chi_sim+eng") -> str:
    return extract_payload(file, enable_ocr=enable_ocr, ocr_lang=ocr_lang, enable_vision=False).get("text", "")

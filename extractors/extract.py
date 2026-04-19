import io
import re
import fitz  # PyMuPDF
import docx
import openpyxl
from pptx import Presentation

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
    0~1，越高越像可讀文本。
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
    """
    簡單前處理：轉灰階 + 自動對比
    （不做過度二值化，避免數理符號/細字變形）
    """
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
        return _clean_text(text)
    except Exception:
        return ""


def _ocr_scanned_pdf_all_pages(data: bytes, lang: str = "chi_tra+chi_sim+eng", zoom: float = 2.5) -> str:
    """
    掃描 PDF OCR：不限制頁數（按你要求）。
    為提升準確度，提高 render zoom（較清晰但更慢）。
    """
    if not OCR_AVAILABLE:
        return ""

    parts = []
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            mat = fitz.Matrix(zoom, zoom)
            for i in range(len(doc)):
                page = doc[i]
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img_bytes = pix.tobytes("png")
                t = _ocr_image_bytes(img_bytes, lang=lang)
                if t:
                    parts.append(t)
    except Exception:
        return ""

    return _clean_text("\n".join(parts))


def extract_text(file, enable_ocr: bool = False, ocr_lang: str = "chi_tra+chi_sim+eng") -> str:
    """
    支援 pdf/docx/txt/xlsx/pptx + png/jpg/jpeg（OCR）
    PDF：
      - 先嘗試直接抽字
      - 若抽到文字太少，且 enable_ocr=True → 當掃描件做 OCR（全頁）
    """
    ext = file.name.split(".")[-1].lower()
    data = file.getvalue()

    try:
        if ext == "pdf":
            text = _extract_pdf_text(data)
            if enable_ocr and len(text) < 50:
                ocr_text = _ocr_scanned_pdf_all_pages(data, lang=ocr_lang)
                # OCR 品質檢測：太垃圾就回傳空（交由上層提示/改用其他方法）
                if _text_quality_score(ocr_text) < 0.25:
                    return ""
                return ocr_text
            return text

        if ext == "docx":
            return _extract_docx_text(data)
        if ext == "txt":
            return _extract_txt_text(data)
        if ext == "xlsx":
            return _extract_xlsx_text(data)
        if ext == "pptx":
            return _extract_pptx_text(data)

        if ext in {"png", "jpg", "jpeg"}:
            if enable_ocr:
                ocr_text = _ocr_image_bytes(data, lang=ocr_lang)
                if _text_quality_score(ocr_text) < 0.25:
                    return ""
                return ocr_text
            return ""

        return ""

    except Exception:
        return ""

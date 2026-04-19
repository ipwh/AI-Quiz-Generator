import io
import re
import fitz  # PyMuPDF
import docx
import openpyxl
from pptx import Presentation

# OCR (optional)
try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False


def _clean_text(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


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


def _ocr_image_bytes(image_bytes: bytes, lang: str = "chi_tra+chi_sim+eng") -> str:
    if not OCR_AVAILABLE:
        return ""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        text = pytesseract.image_to_string(img, lang=lang)
        return _clean_text(text)
    except Exception:
        return ""


def _ocr_scanned_pdf(data: bytes, lang: str = "chi_tra+chi_sim+eng", max_pages: int = 3, zoom: float = 2.0) -> str:
    """
    掃描 PDF OCR：把每頁 render 成影像再做 OCR。
    - max_pages：最多處理前幾頁（避免太慢）
    - zoom：放大倍數（較清晰，但會更慢）
    """
    if not OCR_AVAILABLE:
        return ""

    parts = []
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            page_count = min(len(doc), max_pages)
            mat = fitz.Matrix(zoom, zoom)
            for i in range(page_count):
                page = doc[i]
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img_bytes = pix.tobytes("png")
                t = _ocr_image_bytes(img_bytes, lang=lang)
                if t:
                    parts.append(t)
    except Exception:
        return ""

    return _clean_text("\n".join(parts))


def extract_text(file, enable_ocr: bool = False, ocr_lang: str = "chi_tra+chi_sim+eng", ocr_pdf_pages: int = 3) -> str:
    """
    支援：
      - pdf/docx/txt/xlsx/pptx：一般文字抽取
      - png/jpg/jpeg：若 enable_ocr=True 則 OCR
      - 掃描 pdf：若一般抽取文字太少，且 enable_ocr=True，則 OCR 前幾頁
    """
    ext = file.name.split(".")[-1].lower()
    data = file.getvalue()

    try:
        if ext == "pdf":
            text = _extract_pdf_text(data)
            # 掃描 PDF 判斷：抽到文字太少就當掃描件，轉 OCR
            if enable_ocr and len(text) < 50:
                ocr_text = _ocr_scanned_pdf(data, lang=ocr_lang, max_pages=ocr_pdf_pages)
                return ocr_text or text
            return text

        if ext == "docx":
            return _extract_docx_text(data)
        if ext == "txt":
            return _extract_txt_text(data)
        if ext == "xlsx":
            return _extract_xlsx_text(data)
        if ext == "pptx":
            return _extract_pptx_text(data)

        # 圖片 OCR
        if ext in {"png", "jpg", "jpeg"}:
            if enable_ocr:
                return _ocr_image_bytes(data, lang=ocr_lang)
            return ""

        return ""

    except Exception:
        return ""

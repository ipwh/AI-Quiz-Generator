# extractors/extract.py
# ---------------------------------------------------------
# 目標：香港中學 AI 題目生成器的統一抽取器（文字 / 圖片 / Vision / OCR）
# **本版本說明**：
# ✅ 已【完全移除 Tesseract】
# ✅ OCR 一律使用 PaddleOCR（lang="ch"，通用中文，較穩）
# ✅ 保留：PDF/DOCX/TXT/XLSX/PPTX 抽字、掃描 PDF OCR、Vision 圖片輸出
# ✅ Streamlit Cloud 友善（延遲載入 + cache）
# ---------------------------------------------------------

from __future__ import annotations

import io
import re
import base64
import streamlit as st

# PyMuPDF（新名優先，舊名 fallback）
try:
    import pymupdf as fitz
except Exception:
    import fitz

import docx
import openpyxl
from pptx import Presentation
from PIL import Image

# ---------------------------------------------------------
# PaddleOCR（唯一 OCR 引擎）
# ---------------------------------------------------------
PADDLE_AVAILABLE = False
try:
    from paddleocr import PaddleOCR
    PADDLE_AVAILABLE = True
except Exception:
    PADDLE_AVAILABLE = False


@st.cache_resource(show_spinner=False)
def _get_paddle_ocr():
    """
    建立 PaddleOCR instance（只初始化一次）
    lang="ch"：通用中文（推薦，簡繁混用較穩）
    """
    if not PADDLE_AVAILABLE:
        return None
    return PaddleOCR(
        use_angle_cls=True,
        lang="ch",
        show_log=False,
    )


def _paddle_ocr_image_bytes(image_bytes: bytes) -> str:
    if not PADDLE_AVAILABLE:
        return ""
    ocr = _get_paddle_ocr()
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


# =========================================================
# Data URL helper
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
    s = re.sub(r"[\u3000]+", " ", s)
    return s.strip()


# =========================================================
# File text extractors（非 OCR）
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
# PDF → Image helpers（OCR / Vision 共用）
# =========================================================

def _pdf_page_to_png_bytes(
    page: "fitz.Page",
    dpi: int = 300,
    zoom_fallback: float = 2.5,
) -> bytes:
    try:
        pix = page.get_pixmap(dpi=int(dpi), alpha=False)
    except Exception:
        mat = fitz.Matrix(float(zoom_fallback), float(zoom_fallback))
        pix = page.get_pixmap(matrix=mat, alpha=False)
    return pix.tobytes("png")


def _pdf_pages_to_images_data_url(
    data: bytes,
    max_pages: int = 3,
    zoom: float = 2.0,
):
    imgs = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        n = min(len(doc), max_pages)
        for i in range(n):
            page = doc[i]
            mat = fitz.Matrix(float(zoom), float(zoom))
            pix = page.get_pixmap(matrix=mat, alpha=False)
            imgs.append(bytes_to_data_url(pix.tobytes("png"), "image/png"))
    return imgs


# =========================================================
# Main: extract_payload
# =========================================================

def extract_payload(
    file,
    enable_ocr: bool = False,
    enable_vision: bool = False,
    vision_pdf_max_pages: int = 3,
    # 掃描 PDF OCR 控制（避免全本 OCR）
    ocr_pdf_max_pages: int = 10,
    ocr_pdf_dpi: int = 300,
    ocr_min_text_len_for_skip: int = 50,
) -> dict:
    """
    回傳：{ "text": str, "images": [data_url,...], "meta": {"ext": str} }
    """
    name = getattr(file, "name", "")
    ext = name.split(".")[-1].lower()
    data = file.getvalue()

    out = {"text": "", "images": [], "meta": {"ext": ext}}

    try:
        # -------------------- PDF --------------------
        if ext == "pdf":
            text = _extract_pdf_text(data)
            out["text"] = text

            # 掃描 PDF（抽字太少 → PaddleOCR）
            if enable_ocr and len(text) < int(ocr_min_text_len_for_skip):
                parts = []
                with fitz.open(stream=data, filetype="pdf") as doc:
                    max_pages = min(len(doc), int(ocr_pdf_max_pages))
                    for i in range(max_pages):
                        png_bytes = _pdf_page_to_png_bytes(
                            doc[i], dpi=int(ocr_pdf_dpi)
                        )
                        t = _paddle_ocr_image_bytes(png_bytes)
                        if t:
                            parts.append(t)
                out["text"] = _clean_text("\n".join(parts)) if parts else ""

            if enable_vision:
                out["images"] = _pdf_pages_to_images_data_url(
                    data, max_pages=int(vision_pdf_max_pages)
                )

            return out

        # -------------------- DOCX / TXT / XLSX / PPTX --------------------
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

        # -------------------- Image --------------------
        if ext in {"png", "jpg", "jpeg"}:
            mime = "image/png" if ext == "png" else "image/jpeg"
            if enable_ocr:
                out["text"] = _paddle_ocr_image_bytes(data)
            if enable_vision:
                out["images"] = [bytes_to_data_url(data, mime)]
            return out

        return out
    except Exception:
        return out


# =========================================================
# Vision helper（給多模態 LLM 用）
# =========================================================

def extract_images_for_llm_ocr(
    file,
    pdf_max_pages: int = 3,
    pdf_zoom: float = 2.0,
):
    name = getattr(file, "name", "")
    ext = name.split(".")[-1].lower()
    data = file.getvalue()

    if ext in {"png", "jpg", "jpeg"}:
        mime = "image/png" if ext == "png" else "image/jpeg"
        return [bytes_to_data_url(data, mime)]

    if ext == "pdf":
        return _pdf_pages_to_images_data_url(
            data,
            max_pages=max(1, int(pdf_max_pages)),
            zoom=float(pdf_zoom),
        )

    return []


# =========================================================
# 兼容舊接口
# =========================================================

def extract_text(
    file,
    enable_ocr: bool = False,
) -> str:
    return extract_payload(
        file,
        enable_ocr=enable_ocr,
        enable_vision=False,
    ).get("text", "")


_image_bytes_to_data_url = bytes_to_data_url
_bytes_to_data_url = bytes_to_data_url

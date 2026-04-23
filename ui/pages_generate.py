import streamlit as st
import requests

# ============================================================
# Vision OCR 強化版 Generate Page（方案 C：真正 OCR 級別・穩定版）
# - OpenCV 前處理（提升對比 / 二值化）
# - Tesseract 本地 OCR 作為強力後備（離線）
# - Vision OCR（LLM）只作補文字（安全、不污染出題）
# - ✅ 保證通過 python -m py_compile
# ============================================================

from extractors.extract import extract_payload, extract_images_for_llm_ocr
from core.question_mapper import dicts_to_items, items_to_editor_df, editor_df_to_items
from core.validators import validate_questions
from ui.components_editor import render_editor
from ui.components_export import render_export_panel
from services.llm_service import generate_questions

# Optional heavy deps (safe import)
try:
    import cv2
    import numpy as np
    _HAS_CV = True
except Exception:
    _HAS_CV = False

try:
    import pytesseract
    _HAS_TESS = True
except Exception:
    _HAS_TESS = False

DNL = chr(10) * 2

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def _split_paragraphs(text: str):
    return [p.strip() for p in (text or "").split(DNL) if p.strip()]


def _build_text_with_highlights(raw_text: str, marked_idx: set, limit: int):
    paras = _split_paragraphs(raw_text)
    highlights = [paras[i] for i in range(len(paras)) if i in marked_idx]
    others = [paras[i] for i in range(len(paras)) if i not in marked_idx]
    blocks = []
    if highlights:
        blocks.append("[FOCUS]")
        blocks.extend(highlights)
    if others:
        blocks.append("[OTHER]")
        blocks.extend(others)
    text = DNL.join(blocks)
    return text[:limit] if limit else text


# -------- Vision OCR (LLM) --------

def _vision_ocr_text(cfg: dict, images_data_urls: list, fast_mode: bool = True) -> str:
    """Best-effort Vision OCR via LLM Vision. Return empty string on failure."""
    if not images_data_urls or not isinstance(cfg, dict):
        return ""

    prompt = (
        "你是一個 OCR 文字抽取器。請從圖片中抽取所有可辨識文字，輸出純文字即可。\n"
        "規則：\n"
        "- 不要解釋、不要總結、不要加入推測\n"
        "- 盡量保留段落與換行\n"
    )

    content = [{"type": "text", "text": prompt}]
    for url in images_data_urls:
        content.append({"type": "image_url", "image_url": {"url": url, "detail": "high"}})

    temperature = 0.0
    max_tokens = 1200 if fast_mode else 2000
    timeout = 90 if fast_mode else 150

    try:
        if cfg.get("type") == "azure":
            endpoint = (cfg.get("endpoint") or "").rstrip("/")
            deployment = cfg.get("deployment")
            api_version = cfg.get("api_version") or "2024-02-15-preview"
            if not endpoint or not deployment:
                return ""
            url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
            headers = {"api-key": cfg.get("api_key", ""), "Content-Type": "application/json"}
            payload = {
                "messages": [{"role": "user", "content": content}],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        else:
            base_url = (cfg.get("base_url") or "").rstrip("/")
            model = cfg.get("model")
            if not base_url or not model:
                return ""
            url = f"{base_url}/chat/completions"
            headers = {
                "Authorization": f"Bearer {cfg.get('api_key','')}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        out = (((data.get("choices") or [])[0] or {}).get("message") or {}).get("content", "")
        return (out or "").strip()
    except Exception:
        return ""


# -------- True OCR (OpenCV + Tesseract) --------

def _preprocess_image_for_ocr(img_bgr):
    if not _HAS_CV:
        return img_bgr
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return th


def _tesseract_ocr_from_images(images_bgr) -> str:
    if not (_HAS_TESS and _HAS_CV) or not images_bgr:
        return ""
    texts = []
    for img in images_bgr:
        try:
            proc = _preprocess_image_for_ocr(img)
            txt = pytesseract.image_to_string(proc, lang="chi_tra+eng")
            if txt.strip():
                texts.append(txt)
        except Exception:
            pass
    return "\n".join(texts).strip()


# ------------------------------------------------------------
# Page
# ------------------------------------------------------------

def render_generate_tab(ctx: dict):
    cfg = ctx["api_config"]()
    can_call_ai = ctx["can_call_ai"]
    subject = ctx["subject"]
    level_code = ctx["level_code"]
    question_count = ctx["question_count"]
    fast_mode = ctx.get("fast_mode", True)
    ocr_mode = ctx.get("ocr_mode")
    vision_pdf_max_pages = int(ctx.get("vision_pdf_max_pages", 3))

    st.markdown("## ① 上載教材")
    file = st.file_uploader(
        "上載教材",
        type=["pdf", "docx", "txt", "pptx", "xlsx", "png", "jpg", "jpeg"],
        key="gen_source_file",
    )

    raw_text, images, images_bgr = "", [], []

    if file:
        payload = extract_payload(file)
        raw_text = payload.get("text", "") or ""
        images = payload.get("images", []) or []

        if ocr_mode in ("🔬 本地 OCR（掃描 PDF/圖片，離線）", "🤖 Vision OCR（把圖片轉文字，較準）") and not images:
            images = extract_images_for_llm_ocr(file, pdf_max_pages=vision_pdf_max_pages) or []

        if images and _HAS_CV:
            import base64
            for u in images:
                try:
                    _, b64 = u.split(",", 1)
                    data = base64.b64decode(b64)
                    arr = np.frombuffer(data, dtype=np.uint8)
                    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    if img is not None:
                        images_bgr.append(img)
                except Exception:
                    pass

        if ocr_mode == "🤖 Vision OCR（把圖片轉文字，較準）" and images:
            raw_text += DNL + _vision_ocr_text(cfg, images, fast_mode)
        elif ocr_mode == "🔬 本地 OCR（掃描 PDF/圖片，離線）" and images_bgr:
            raw_text += DNL + _tesseract_ocr_from_images(images_bgr)

    st.markdown("## ② 標記重點段落（可選）")
    paras = _split_paragraphs(raw_text)
    marked = set(range(len(paras)))

    for i, p in enumerate(paras):
        label = p.replace("\n", " ")
        label = (label[:160] + "…") if len(label) > 160 else label
        if not st.checkbox(label, value=True, key=f"gen_mark_{i}"):
            marked.discard(i)

    st.markdown("## ③ 生成題目")
    if st.button("🪄 生成題目"):
        text_for_ai = _build_text_with_highlights(raw_text, marked, 10000)
        data = generate_questions(
            cfg=cfg,
            text=text_for_ai,
            subject=subject,
            level=level_code,
            question_count=question_count,
            fast_mode=fast_mode,
        )
        items = dicts_to_items(data, subject=subject, source="generate")
        st.session_state["generated_items"] = items

    if st.session_state.get("generated_items"):
        df = items_to_editor_df(st.session_state["generated_items"])
        edited_df, selected_df = render_editor(df, key="editor_generate")
        render_export_panel(selected_df, subject, st.session_state.get("google_creds"), prefix="generate")

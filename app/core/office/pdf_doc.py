"""PDF 预览与文本读取（pypdfium2 / PDFium，Apache-2.0 OR BSD-3-Clause）。"""
from __future__ import annotations

import base64
import io
from pathlib import Path

import pypdfium2 as pdfium

MAX_PAGES_RENDER = 500
DEFAULT_ZOOM = 1.6
MAX_ZOOM = 4.0


def info(path: Path) -> dict:
    pdf = pdfium.PdfDocument(str(path))
    try:
        if len(pdf) <= 0:
            return {"pages": 0, "width": 0.0, "height": 0.0}
        width, height = pdf[0].get_size()
        return {
            "pages": len(pdf),
            "width": round(float(width), 1),
            "height": round(float(height), 1),
        }
    finally:
        pdf.close()


def render_page(path: Path, index: int = 0, zoom: float = DEFAULT_ZOOM) -> dict:
    pdf = pdfium.PdfDocument(str(path))
    try:
        total = len(pdf)
        if total <= 0:
            return {"ok": False, "error": "PDF 没有页面"}
        index = max(0, min(int(index), total - 1))
        scale = max(0.5, min(float(zoom or DEFAULT_ZOOM), MAX_ZOOM))
        page = pdf[index]
        bitmap = page.render(scale=scale)
        try:
            image = bitmap.to_pil()
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            png = buf.getvalue()
            width, height = image.size
        finally:
            bitmap.close()
        return {
            "ok": True,
            "page": index,
            "pages": total,
            "zoom": round(scale, 2),
            "width": width,
            "height": height,
            "data_url": "data:image/png;base64," + base64.b64encode(png).decode(),
        }
    finally:
        pdf.close()


def text(path: Path, max_pages: int = 40, max_chars: int = 12000) -> dict:
    pdf = pdfium.PdfDocument(str(path))
    try:
        total = len(pdf)
        pages = []
        used = 0
        for i in range(min(total, max(1, max_pages))):
            page = pdf[i]
            textpage = page.get_textpage()
            try:
                piece = textpage.get_text_range() or ""
            finally:
                textpage.close()
            if used + len(piece) > max_chars:
                piece = piece[: max(0, max_chars - used)]
                pages.append({"page": i + 1, "text": piece})
                break
            pages.append({"page": i + 1, "text": piece})
            used += len(piece)
            if used >= max_chars:
                break
        return {
            "ok": True,
            "pages": total,
            "returned_pages": len(pages),
            "truncated": len(pages) < total or used >= max_chars,
            "content": pages,
        }
    finally:
        pdf.close()

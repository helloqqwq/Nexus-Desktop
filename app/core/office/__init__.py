"""办公文件（PDF / Word / Excel / PowerPoint）读取、预览与生成。"""
from __future__ import annotations

from pathlib import Path

from . import docx_doc, html2pptx, pdf_doc, pptx_doc, xlsx_doc

__all__ = ["docx_doc", "html2pptx", "pdf_doc", "pptx_doc", "xlsx_doc",
           "kind_of", "read_any"]

KIND_BY_SUFFIX = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "docx",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".xls": "xlsx",
    ".pptx": "pptx",
    ".ppt": "pptx",
}


def kind_of(path: Path | str) -> str:
    return KIND_BY_SUFFIX.get(Path(path).suffix.lower(), "")


def read_any(path: Path, **kwargs) -> dict:
    kind = kind_of(path)
    if kind == "pdf":
        return pdf_doc.text(path, max_chars=int(kwargs.get("max_chars") or 12000))
    if kind == "docx":
        return docx_doc.text(path, max_chars=int(kwargs.get("max_chars") or 14000))
    if kind == "xlsx":
        return xlsx_doc.read(path, sheet=kwargs.get("sheet"),
                             max_rows=int(kwargs.get("max_rows") or 60),
                             max_cols=int(kwargs.get("max_cols") or 24))
    if kind == "pptx":
        return pptx_doc.read(path, max_chars=int(kwargs.get("max_chars") or 12000))
    return {"ok": False, "error": "不支持的办公文件类型：" + path.suffix}

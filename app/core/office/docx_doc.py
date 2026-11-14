"""Word 读取（转 HTML）与文本级写回。"""
from __future__ import annotations

import base64
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from docx.table import Table
from docx.text.paragraph import Paragraph

IMAGE_MAX_BYTES = 4 * 1024 * 1024

_ALIGN = {
    WD_ALIGN_PARAGRAPH.LEFT: "left",
    WD_ALIGN_PARAGRAPH.CENTER: "center",
    WD_ALIGN_PARAGRAPH.RIGHT: "right",
    WD_ALIGN_PARAGRAPH.JUSTIFY: "justify",
}

_STYLE_TAGS = {
    "title": ("h1", "doc-title"),
    "subtitle": ("p", "doc-subtitle"),
    "heading 1": ("h2", "doc-h1"),
    "heading 2": ("h3", "doc-h2"),
    "heading 3": ("h4", "doc-h3"),
    "heading 4": ("h5", "doc-h4"),
    "heading 5": ("h6", "doc-h5"),
    "heading 6": ("h6", "doc-h6"),
    "list bullet": ("p", "doc-li"),
    "list number": ("p", "doc-li doc-li-num"),
    "quote": ("blockquote", "doc-quote"),
    "intense quote": ("blockquote", "doc-quote"),
}


def _esc(text: str) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _color(run) -> str:
    try:
        rgb = run.font.color.rgb
        return "#" + str(rgb).lower() if rgb else ""
    except Exception:
        return ""


def _run_html(run, doc) -> tuple[str, list[str]]:
    text = run.text or ""
    images: list[str] = []
    for drawing in run._element.findall(".//" + qn("w:drawing")):
        for blip in drawing.findall(".//" + qn("a:blip")):
            rid = blip.get(qn("r:embed"))
            if not rid:
                continue
            try:
                part = doc.part.related_parts[rid]
                if len(part.blob) > IMAGE_MAX_BYTES:
                    continue
                mime = part.content_type or "image/png"
                images.append("data:" + mime + ";base64," + base64.b64encode(part.blob).decode())
            except Exception:
                continue
    if not text:
        return "", images
    html = _esc(text)
    if run.bold:
        html = "<strong>" + html + "</strong>"
    if run.italic:
        html = "<em>" + html + "</em>"
    if run.underline:
        html = "<u>" + html + "</u>"
    if run.font.strike:
        html = "<s>" + html + "</s>"
    styles = []
    color = _color(run)
    if color:
        styles.append("color:" + color)
    size = run.font.size.pt if run.font.size else None
    if size and abs(size - 11) > 0.2:
        styles.append(f"font-size:{round(size, 1)}pt")
    name = run.font.name
    if name and name.lower() not in ("calibri", "宋体", "等线"):
        styles.append("font-family:'" + name.replace("'", "") + "'")
    if styles:
        html = '<span style="' + ";".join(styles) + '">' + html + "</span>"
    return html, images


def _paragraph_html(p, doc) -> tuple[str, str]:
    style = (p.style.name or "").lower() if p.style is not None else ""
    tag, cls = _STYLE_TAGS.get(style, ("p", "doc-p"))
    if style.startswith("heading ") and not cls.startswith("doc-h"):
        try:
            level = int(style.split()[-1]) + 1
        except ValueError:
            level = 2
        tag, cls = "h" + str(min(max(level, 2), 6)), "doc-h" + str(min(max(level - 1, 1), 5))
    if style.startswith("list number"):
        cls = "doc-li doc-li-num"
    align = _ALIGN.get(p.alignment) if p.alignment is not None else None
    attr = ' class="' + cls + '"'
    if align:
        attr += ' data-align="' + align + '"'
    parts = []
    images: list[str] = []
    for run in p.runs:
        html, imgs = _run_html(run, doc)
        parts.append(html)
        images.extend(imgs)
    if style.startswith("list bullet") and not "".join(parts).lstrip().startswith("•"):
        parts.insert(0, "• ")
    if style.startswith("list number") and not "".join(parts).lstrip().startswith(("1.", "•")):
        parts.insert(0, "◦ ")
    inner = "".join(parts) or "&nbsp;"
    if images:
        inner += "".join('<img class="doc-img" src="' + src + '" alt="">' for src in images)
    return tag, "<" + tag + attr + ">" + inner + "</" + tag + ">"


def _table_html(table: Table) -> str:
    rows = []
    for row in table.rows:
        cells = []
        for cell in row.cells:
            text = "\n".join(p.text for p in cell.paragraphs).strip()
            cells.append("<td>" + _esc(text).replace("\n", "<br>") + "</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return '<table class="doc-table"><tbody>' + "".join(rows) + "</tbody></table>"


def to_html(path: Path) -> dict:
    doc = Document(str(path))
    body = doc.element.body
    html_parts: list[str] = []
    blocks: list[dict] = []
    para_index = 0
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            p = Paragraph(child, doc)
            tag, html = _paragraph_html(p, doc)
            html_parts.append(html)
            blocks.append({
                "index": para_index,
                "tag": tag,
                "text": p.text or "",
                "style": p.style.name if p.style is not None else "",
                "size": round(max([r.font.size.pt for r in p.runs if r.font.size] or [0]), 1),
                "bold": any(bool(r.bold) for r in p.runs),
                "align": _ALIGN.get(p.alignment) if p.alignment is not None else "",
            })
            para_index += 1
        elif child.tag == qn("w:tbl"):
            html_parts.append(_table_html(Table(child, doc)))
    section = doc.sections[0] if doc.sections else None
    return {
        "ok": True,
        "html": "".join(html_parts),
        "blocks": blocks,
        "paragraphs": para_index,
        "page": {
            "width": round((section.page_width.inches if section and section.page_width else 8.27), 2),
            "height": round((section.page_height.inches if section and section.page_height else 11.69), 2),
            "margin": round((section.left_margin.inches if section and section.left_margin else 1.0), 2),
        },
    }


def _apply_text(paragraph, text: str) -> None:
    text = str(text or "")
    if not paragraph.runs:
        paragraph.add_run(text)
        return
    paragraph.runs[0].text = text
    for run in paragraph.runs[1:]:
        run.text = ""


def update_paragraphs(path: Path, updates: list[dict]) -> dict:
    doc = Document(str(path))
    paragraphs = doc.paragraphs
    changed = 0
    for item in updates or []:
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        if index < 0 or index >= len(paragraphs):
            continue
        _apply_text(paragraphs[index], item.get("text", ""))
        changed += 1
    if changed:
        doc.save(str(path))
    return {"ok": True, "updated": changed}


def create(path: Path, title: str, blocks: list[dict]) -> dict:
    doc = Document()
    section = doc.sections[0]
    section.left_margin = section.right_margin = Inches(1.0)
    section.top_margin = section.bottom_margin = Inches(0.9)
    normal = doc.styles["Normal"]
    normal.font.name = "Microsoft YaHei"
    normal.font.size = Pt(11)
    normal.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    for level in range(1, 4):
        style = doc.styles[f"Heading {level}"]
        style.font.name = "Microsoft YaHei"
        style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        style.font.color.rgb = RGBColor(0x1F, 0x2A, 0x44)
        style.font.size = Pt({1: 20, 2: 15, 3: 12.5}[level])
        style.font.bold = True
    props = doc.core_properties
    props.title = title or path.stem
    props.author = "Nexus"

    if title:
        cover = doc.add_paragraph()
        cover.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = cover.add_run(title)
        run.bold = True
        run.font.size = Pt(26)
        run.font.color.rgb = RGBColor(0x14, 0x1B, 0x2D)
        doc.add_paragraph()

    for block in blocks or []:
        kind = str(block.get("type") or "paragraph").lower()
        text = str(block.get("text") or "")
        if kind in ("heading", "h"):
            level = max(1, min(int(block.get("level") or 1), 4))
            doc.add_heading(text, level=level)
        elif kind in ("bullet", "list"):
            for line in text.splitlines() or [""]:
                p = doc.add_paragraph(style="List Bullet")
                p.add_run(line)
        elif kind in ("number", "ordered"):
            for line in text.splitlines() or [""]:
                p = doc.add_paragraph(style="List Number")
                p.add_run(line)
        elif kind == "quote":
            p = doc.add_paragraph(style="Intense Quote")
            p.add_run(text)
        elif kind == "table":
            rows = block.get("rows") or []
            if not rows:
                continue
            first = rows[0]
            table = doc.add_table(rows=len(rows), cols=len(first))
            table.style = "Table Grid"
            for r, row in enumerate(rows):
                for c, value in enumerate(row):
                    cell = table.cell(r, c)
                    cell.text = str(value if value is not None else "")
                    if r == 0:
                        for run in cell.paragraphs[0].runs:
                            run.bold = True
            doc.add_paragraph()
        elif kind == "image":
            src = str(block.get("path") or "")
            if not src:
                continue
            width = block.get("width")
            try:
                run = doc.add_paragraph().add_run()
                run.add_picture(src, width=Inches(float(width or 5.6)))
            except Exception:
                continue
        elif kind == "page_break":
            doc.add_page_break()
        else:
            for line in text.split("\n"):
                p = doc.add_paragraph()
                p.add_run(line)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return {"ok": True, "path": str(path)}


def text(path: Path, max_chars: int = 14000) -> dict:
    doc = Document(str(path))
    parts = []
    blocks = []
    for i, p in enumerate(doc.paragraphs):
        if p.text.strip():
            parts.append(p.text)
            blocks.append({"index": i, "text": p.text[:400]})
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip().replace("\n", " ") for c in row.cells]
            parts.append(" | ".join(cells))
    joined = "\n".join(parts)
    return {
        "ok": True,
        "content": joined[:max_chars],
        "truncated": len(joined) > max_chars,
        "paragraphs": len(doc.paragraphs),
        "blocks": blocks[:300],
        "tables": len(doc.tables),
    }

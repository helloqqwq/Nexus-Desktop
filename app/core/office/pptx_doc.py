"""PowerPoint 读取（按页几何渲染）与文本级写回、原生生成。"""
from __future__ import annotations

import base64
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_SHAPE_TYPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Emu, Inches, Pt

IMAGE_MAX_BYTES = 3 * 1024 * 1024
SLIDE_W_IN = 13.333
SLIDE_H_IN = 7.5
EMU_PER_INCH = 914400

_FONT = "Microsoft YaHei"
INK = RGBColor(0x11, 0x18, 0x27)
MUTED = RGBColor(0x5B, 0x64, 0x72)
NAVY = RGBColor(0x1B, 0x24, 0x3B)
ACCENT = RGBColor(0x2F, 0x6B, 0xFF)
SOFT = RGBColor(0xF3, 0xF5, 0xF9)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

_ALIGN = {PP_ALIGN.LEFT: "left", PP_ALIGN.CENTER: "center",
          PP_ALIGN.RIGHT: "right", PP_ALIGN.JUSTIFY: "justify"}
_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
         "gif": "image/gif", "bmp": "image/bmp", "webp": "image/webp",
         "svg": "image/svg+xml", "tiff": "image/tiff"}


def _ratio(value, total) -> float:
    try:
        return round(max(0.0, float(value)) / float(total), 4) if value is not None else 0.0
    except Exception:
        return 0.0


def _color_of(color) -> str:
    try:
        rgb = color.rgb
        return "#" + str(rgb).lower() if rgb else ""
    except Exception:
        return ""


def _fill_of(shape) -> str:
    try:
        fill = shape.fill
        if fill.type is None:
            return ""
        if str(fill.type).startswith("MSO_FILL_TYPE.SOLID") or getattr(fill, "fore_color", None):
            return _color_of(fill.fore_color)
    except Exception:
        return ""
    return ""


def _line_of(shape) -> str:
    try:
        return _color_of(shape.line.color)
    except Exception:
        return ""


def _text_payload(shape) -> list[dict]:
    out = []
    for paragraph in shape.text_frame.paragraphs:
        runs = []
        for run in paragraph.runs:
            if not (run.text or ""):
                continue
            item = {"t": run.text}
            if run.font.bold:
                item["b"] = 1
            if run.font.italic:
                item["i"] = 1
            if run.font.size:
                item["sz"] = round(run.font.size.pt, 1)
            color = _color_of(run.font.color)
            if color:
                item["c"] = color
            name = run.font.name
            if name:
                item["f"] = name
            runs.append(item)
        if not runs:
            continue
        align = _ALIGN.get(paragraph.alignment) if paragraph.alignment is not None else None
        line = {"runs": runs, "level": int(paragraph.level or 0)}
        if align:
            line["align"] = align
        out.append(line)
    return out


def _table_payload(shape) -> list[list[str]]:
    rows = []
    for row in shape.table.rows:
        rows.append([cell.text_frame.text.strip().replace("\n", " ") for cell in row.cells])
    return rows


def info(path: Path) -> dict:
    prs = Presentation(str(path))
    title = ""
    if prs.slides:
        try:
            first = prs.slides[0]
            title = first.shapes.title.text.strip() if first.shapes.title else ""
            if not title:
                for shape in first.shapes:
                    if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip():
                        title = shape.text_frame.text.strip().split("\n")[0]
                        break
        except Exception:
            title = ""
    return {
        "ok": True,
        "slides": len(prs.slides),
        "width": round(prs.slide_width / EMU_PER_INCH, 3),
        "height": round(prs.slide_height / EMU_PER_INCH, 3),
        "title": title,
    }


def slide_payload(path: Path, index: int = 0) -> dict:
    prs = Presentation(str(path))
    total = len(prs.slides)
    if total == 0:
        return {"ok": False, "error": "演示文稿没有页面"}
    index = max(0, min(int(index), total - 1))
    slide = prs.slides[index]
    width = prs.slide_width
    height = prs.slide_height
    bg = ""
    try:
        bg = _color_of(slide.background.fill.fore_color)
    except Exception:
        bg = ""
    shapes = []
    for i, shape in enumerate(slide.shapes):
        try:
            x = _ratio(shape.left, width)
            y = _ratio(shape.top, height)
            w = _ratio(shape.width, width)
            h = _ratio(shape.height, height)
        except Exception:
            continue
        item = {"id": i, "x": x, "y": y, "w": w, "h": h}
        if w <= 0 or h <= 0:
            continue
        try:
            if getattr(shape, "image", None) is not None:
                blob = shape.image.blob
                if len(blob) <= IMAGE_MAX_BYTES:
                    ext = (shape.image.ext or "png").lower()
                    item["type"] = "image"
                    item["src"] = ("data:" + _MIME.get(ext, "image/png") + ";base64,"
                                   + base64.b64encode(blob).decode())
                    item["fit"] = "contain"
                    shapes.append(item)
                    continue
        except Exception:
            pass
        try:
            if shape.has_table:
                item["type"] = "table"
                item["table"] = _table_payload(shape)
                shapes.append(item)
                continue
        except Exception:
            pass
        try:
            if shape.has_chart:
                item["type"] = "chart"
                item["text"] = "图表"
                shapes.append(item)
                continue
        except Exception:
            pass
        try:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                item["type"] = "group"
                shapes.append(item)
                continue
        except Exception:
            pass
        if getattr(shape, "has_text_frame", False):
            paragraphs = _text_payload(shape)
            fill = _fill_of(shape)
            line = _line_of(shape)
            if not paragraphs and not fill and not line:
                continue
            item["type"] = "text"
            item["paras"] = paragraphs
            if fill:
                item["fill"] = fill
            if line:
                item["line"] = line
            try:
                anchor = shape.text_frame.vertical_anchor
                if anchor == MSO_ANCHOR.MIDDLE:
                    item["anchor"] = "middle"
                elif anchor == MSO_ANCHOR.BOTTOM:
                    item["anchor"] = "bottom"
            except Exception:
                pass
            try:
                if shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE:
                    item["round"] = 1
            except Exception:
                pass
            shapes.append(item)
            continue
        fill = _fill_of(shape)
        line = _line_of(shape)
        if fill or line:
            item["type"] = "shape"
            item["fill"] = fill
            item["line"] = line
            shapes.append(item)
    notes = ""
    try:
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
    except Exception:
        notes = ""
    return {
        "ok": True,
        "index": index,
        "slides": total,
        "width": round(width / EMU_PER_INCH, 3),
        "height": round(height / EMU_PER_INCH, 3),
        "bg": bg,
        "shapes": shapes,
        "notes": notes,
    }


def _capture(run) -> dict:
    props = {}
    try:
        if run.font.size:
            props["size"] = run.font.size
        if run.font.bold is not None:
            props["bold"] = run.font.bold
        if run.font.italic is not None:
            props["italic"] = run.font.italic
        if run.font.name:
            props["name"] = run.font.name
        color = run.font.color
        if color and color.rgb:
            props["color"] = color.rgb
    except Exception:
        pass
    return props


def _apply(props: dict, run) -> None:
    if "size" in props:
        run.font.size = props["size"]
    if "bold" in props:
        run.font.bold = props["bold"]
    if "italic" in props:
        run.font.italic = props["italic"]
    if "name" in props:
        run.font.name = props["name"]
    if "color" in props:
        try:
            run.font.color.rgb = props["color"]
        except Exception:
            pass


def _set_frame_text(tf, text: str) -> None:
    lines = str(text or "").split("\n")
    paragraphs = list(tf.paragraphs)
    template = None
    for paragraph in paragraphs:
        if paragraph.runs:
            template = _capture(paragraph.runs[0])
            break
    if len(lines) == len(paragraphs) and paragraphs:
        for paragraph, line in zip(paragraphs, lines):
            if not paragraph.runs:
                run = paragraph.add_run()
                run.text = line
                _apply(template or {}, run)
                continue
            paragraph.runs[0].text = line
            for run in paragraph.runs[1:]:
                run.text = ""
        return
    tf.text = "\n".join(lines)
    for paragraph in tf.paragraphs:
        for run in paragraph.runs:
            _apply(template or {}, run)


def update_texts(path: Path, updates: list[dict]) -> dict:
    prs = Presentation(str(path))
    changed = 0
    for item in updates or []:
        try:
            slide = prs.slides[int(item.get("slide"))]
            shape = slide.shapes[int(item.get("shape"))]
        except (IndexError, TypeError, ValueError):
            continue
        if not getattr(shape, "has_text_frame", False):
            continue
        _set_frame_text(shape.text_frame, item.get("text", ""))
        changed += 1
    if changed:
        prs.save(str(path))
    return {"ok": True, "updated": changed}


def read(path: Path, max_chars: int = 12000) -> dict:
    prs = Presentation(str(path))
    pages = []
    used = 0
    for i, slide in enumerate(prs.slides):
        lines = []
        shapes = []
        for shape_index, shape in enumerate(slide.shapes):
            text = ""
            if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip():
                text = shape.text_frame.text.strip()
                lines.append(text)
                shapes.append({"shape": shape_index, "text": text[:600]})
            elif getattr(shape, "has_table", False):
                rows = []
                for row in shape.table.rows:
                    rows.append(" | ".join(c.text_frame.text.strip() for c in row.cells))
                lines.extend(rows)
                shapes.append({"shape": shape_index, "table": rows[:12]})
        text = "\n".join(lines)
        used += len(text)
        pages.append({"slide": i + 1, "text": text[:2000], "shapes": shapes})
        if used >= max_chars:
            break
    return {
        "ok": True,
        "slides": len(prs.slides),
        "returned": len(pages),
        "truncated": len(pages) < len(prs.slides) or used >= max_chars,
        "content": pages,
    }


# ---------------- 原生生成 ----------------

def _hex_rgb(value: str):
    text = str(value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        return None
    try:
        return RGBColor(int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return None


def _luminance(color) -> float:
    try:
        return (0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]) / 255.0
    except Exception:
        return 1.0


def _blank(prs: Presentation):
    return prs.slides.add_slide(prs.slide_layouts[6])


def _textbox(slide, x, y, w, h, text, size=16, color=INK, bold=False,
             align=PP_ALIGN.LEFT, font=_FONT, spacing=1.0):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    lines = str(text or "").split("\n")
    for i, line in enumerate(lines):
        paragraph = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        paragraph.alignment = align
        paragraph.line_spacing = spacing
        run = paragraph.add_run()
        run.text = line
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = color
        run.font.name = font
    return box


def _para(slide, x, y, w, h, text, size=15, color=INK, bold=False,
          bullet=False, align=PP_ALIGN.LEFT, spacing=1.35):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    lines = [line for line in str(text or "").split("\n") if line.strip()]
    for i, line in enumerate(lines):
        paragraph = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        paragraph.alignment = align
        paragraph.line_spacing = spacing
        paragraph.space_after = Pt(6)
        if bullet:
            paragraph.level = 0
            p = paragraph._p
            pPr = p.get_or_add_pPr()
            buChar = pPr.makeelement("{http://schemas.openxmlformats.org/drawingml/2006/main}buChar", {"char": "•"})
            pPr.append(buChar)
            pPr.set("marL", str(int(Inches(0.28))))
            pPr.set("indent", str(int(-Inches(0.22))))
        run = paragraph.add_run()
        run.text = line
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = color
        run.font.name = _FONT
    return box


def _bar(slide, x, y, w, h, color) -> None:
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    shape.shadow.inherit = False


def _footer(slide, index: int, total: int) -> None:
    _textbox(slide, 0.62, 7.06, 6.0, 0.24, "Nexus", size=9, color=MUTED)
    _textbox(slide, 11.9, 7.06, 0.8, 0.24, f"{index:02d} / {total:02d}",
             size=9, color=MUTED, align=PP_ALIGN.RIGHT)


def _set_bg(slide, color) -> None:
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def _picture(slide, src: str, box: tuple[float, float, float, float], contain=True):
    x, y, w, h = box
    try:
        pic = slide.shapes.add_picture(src, Inches(x), Inches(y), Inches(w), Inches(h))
    except Exception:
        return None
    if contain:
        try:
            ratio = pic.image.width / pic.image.height
            target = w / h
            if ratio > target:
                new_h = w / ratio
                pic.top = Inches(y + (h - new_h) / 2)
                pic.height = Inches(new_h)
            else:
                new_w = h * ratio
                pic.left = Inches(x + (w - new_w) / 2)
                pic.width = Inches(new_w)
        except Exception:
            pass
    return pic


def _add_table(slide, rows: list[list], x, y, w, max_h=5.0) -> None:
    rows = [r for r in (rows or []) if r]
    if not rows:
        return
    cols = max(len(r) for r in rows)
    norm = [[str(c if c is not None else "") for c in (row + [""] * (cols - len(row)))] for row in rows]
    height = min(max_h, 0.42 * len(norm))
    table = slide.shapes.add_table(len(norm), cols, Inches(x), Inches(y), Inches(w), Inches(height)).table
    for r, row in enumerate(norm):
        for c, value in enumerate(row):
            cell = table.cell(r, c)
            cell.text = value
            cell.margin_left = Inches(0.08)
            cell.margin_right = Inches(0.08)
            for paragraph in cell.text_frame.paragraphs:
                paragraph.font.size = Pt(12 if r else 12.5)
                paragraph.font.name = _FONT
                paragraph.font.bold = r == 0
                paragraph.font.color.rgb = WHITE if r == 0 else INK
            cell.fill.solid()
            cell.fill.fore_color.rgb = NAVY if r == 0 else (SOFT if r % 2 else WHITE)


def _cover(prs, spec: dict, index: int, total: int) -> None:
    slide = _blank(prs)
    bg = _hex_rgb(spec.get("bg")) or NAVY
    _set_bg(slide, bg)
    dark = _luminance(bg) < 0.5
    ink = _hex_rgb(spec.get("fg")) or (WHITE if dark else NAVY)
    accent = _hex_rgb(spec.get("accent")) or ACCENT
    sub = RGBColor(0xC7, 0xD2, 0xE6) if dark else MUTED
    _bar(slide, 0.9, 2.0, 0.9, 0.09, accent)
    _textbox(slide, 0.9, 2.35, 10.8, 1.6, spec.get("title") or "", size=40, color=ink, bold=True)
    subtitle = str(spec.get("subtitle") or "")
    if subtitle:
        _textbox(slide, 0.9, 4.15, 9.6, 1.1, subtitle, size=18, color=sub)
    _textbox(slide, 0.9, 6.55, 6.0, 0.3, spec.get("footer") or "", size=10,
             color=RGBColor(0x8B, 0x99, 0xB2) if dark else MUTED)


def _section(prs, spec: dict, index: int, total: int) -> None:
    slide = _blank(prs)
    bg = _hex_rgb(spec.get("bg")) or SOFT
    _set_bg(slide, bg)
    dark = _luminance(bg) < 0.5
    ink = _hex_rgb(spec.get("fg")) or (WHITE if dark else NAVY)
    accent = _hex_rgb(spec.get("accent")) or ACCENT
    _textbox(slide, 0.9, 2.7, 1.6, 1.0, f"{index:02d}", size=54, color=accent, bold=True)
    _textbox(slide, 0.9, 3.85, 10.6, 0.9, spec.get("title") or "", size=30, color=ink, bold=True)
    if spec.get("subtitle"):
        _textbox(slide, 0.9, 4.7, 9.8, 0.7, spec["subtitle"], size=14,
                 color=RGBColor(0xC7, 0xD2, 0xE6) if dark else MUTED)
    _footer(slide, index, total)


def _content(prs, spec: dict, index: int, total: int) -> None:
    slide = _blank(prs)
    bg = _hex_rgb(spec.get("bg")) or WHITE
    _set_bg(slide, bg)
    dark = _luminance(bg) < 0.5
    ink = _hex_rgb(spec.get("fg")) or (WHITE if dark else NAVY)
    body_ink = RGBColor(0xDF, 0xE6, 0xF2) if dark else INK
    accent = _hex_rgb(spec.get("accent")) or ACCENT
    _textbox(slide, 0.75, 0.6, 11.9, 0.8, spec.get("title") or "", size=30, color=ink, bold=True)
    _bar(slide, 0.78, 1.45, 0.7, 0.06, accent)
    body = spec.get("bullets") or []
    if isinstance(body, str):
        body = [body]
    paragraphs = spec.get("paragraphs") or []
    text_lines = ([spec["subtitle"]] if spec.get("subtitle") else []) + list(paragraphs) + list(body)
    images = spec.get("images") or ([spec["image"]] if spec.get("image") else [])
    if images:
        _para(slide, 0.78, 1.9, 6.3, 4.8, "\n".join(text_lines), size=16, bullet=bool(body),
              color=body_ink)
        _picture(slide, images[0], (7.35, 1.9, 5.2, 4.6))
    else:
        _para(slide, 0.78, 1.9, 11.7, 4.9, "\n".join(text_lines), size=16, bullet=bool(body),
              color=body_ink)
    if spec.get("table"):
        _add_table(slide, spec["table"].get("rows") if isinstance(spec["table"], dict) else spec["table"],
                   0.78, 1.95, 11.7)
    _footer(slide, index, total)
    _notes(slide, spec.get("notes"))


def _notes(slide, notes) -> None:
    if not notes:
        return
    try:
        slide.notes_slide.notes_text_frame.text = str(notes)
    except Exception:
        pass


def _closing(prs, spec: dict, index: int, total: int) -> None:
    slide = _blank(prs)
    bg = _hex_rgb(spec.get("bg")) or NAVY
    _set_bg(slide, bg)
    dark = _luminance(bg) < 0.5
    ink = _hex_rgb(spec.get("fg")) or (WHITE if dark else NAVY)
    _textbox(slide, 0.9, 2.9, 11.4, 1.1, spec.get("title") or "谢谢", size=44, color=ink,
             bold=True, align=PP_ALIGN.CENTER)
    if spec.get("subtitle"):
        _textbox(slide, 0.9, 4.2, 11.4, 0.8, spec["subtitle"], size=16,
                 color=RGBColor(0xC7, 0xD2, 0xE6) if dark else MUTED, align=PP_ALIGN.CENTER)


def _infer_layout(spec: dict, index: int, total: int) -> str:
    explicit = str(spec.get("layout") or "").lower()
    if explicit in ("cover", "section", "content", "closing", "table"):
        return explicit
    if spec.get("table"):
        return "content"
    if index == 0 and not spec.get("bullets") and not spec.get("paragraphs"):
        return "cover"
    if index == total - 1 and (spec.get("title") or "").strip() in ("谢谢", "Thank you", "Q&A"):
        return "closing"
    return "content"


def create(path: Path, slides: list[dict], title: str = "") -> dict:
    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W_IN)
    prs.slide_height = Inches(SLIDE_H_IN)
    total = len(slides or [])
    for index, spec in enumerate(slides or []):
        _render_spec(prs, spec, index, total)
    if not slides:
        _blank(prs)
    if title:
        try:
            prs.core_properties.title = title
        except Exception:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(path))
    return {"ok": True, "path": str(path), "slides": len(prs.slides)}


def _render_spec(prs, spec: dict, index: int, total: int) -> None:
    layout = _infer_layout(spec, index, total)
    if layout == "cover":
        _cover(prs, spec, index + 1, total)
    elif layout == "section":
        _section(prs, spec, index + 1, total)
    elif layout == "closing":
        _closing(prs, spec, index + 1, total)
    else:
        _content(prs, spec, index + 1, total)


def append(path: Path, slides: list[dict]) -> dict:
    prs = Presentation(str(path))
    start = len(prs.slides)
    total = start + len(slides or [])
    for i, spec in enumerate(slides or []):
        _render_spec(prs, spec, start + i, total)
    prs.save(str(path))
    return {"ok": True, "appended": len(slides or []), "slides": len(prs.slides)}

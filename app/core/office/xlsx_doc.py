"""Excel 读取与原地写入。

显示用 openpyxl 读取；保存时直接改压缩包里的 worksheet XML，保留图表、图片、
条件格式等 openpyxl 无法完整往返的内容。
"""
from __future__ import annotations

import datetime as _dt
import os
import posixpath
import re
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
ET.register_namespace("", NS)
ET.register_namespace("r", REL_NS)
ET.register_namespace("pr", PKG_REL_NS)

MAX_ROWS = 300
MAX_COLS = 40


def _col_index(letters: str) -> int:
    value = 0
    for ch in letters:
        value = value * 26 + (ord(ch.upper()) - 64)
    return max(1, value)


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat(sep=" ") if isinstance(value, _dt.datetime) else value.isoformat()
    return str(value)


def _argb(color) -> str:
    if color is None:
        return ""
    rgb = getattr(color, "rgb", None)
    if isinstance(rgb, str) and len(rgb) in (6, 8):
        return "#" + rgb[-6:].lower()
    return ""


def _fill(cell) -> str:
    fill = getattr(cell, "fill", None)
    if fill is None or not getattr(fill, "fill_type", None):
        return ""
    if fill.fill_type != "solid":
        return ""
    return _argb(getattr(fill, "fgColor", None))


def _decimals(fmt: str) -> int:
    match = re.search(r"\.([0#]+)", fmt or "")
    return len(match.group(1)) if match else 0


def _format_number(value, fmt: str) -> str:
    """按 Excel 数字格式做轻量显示：百分比、货币、千分位、小数位。"""
    fmt = fmt or "General"
    if fmt in ("General", "@"):
        return _cell_text(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _cell_text(value)
    decimals = _decimals(fmt)
    if "%" in fmt:
        return f"{number * 100:.{decimals}f}%"
    prefix = "¥" if ("¥" in fmt or "￥" in fmt) else ("$" if "$" in fmt else "")
    grouped = "#,##0" in fmt or "," in fmt.split(";")[0]
    if grouped:
        text = f"{number:,.{decimals}f}"
    elif decimals:
        text = f"{number:.{decimals}f}"
    else:
        text = str(int(number)) if float(number).is_integer() else f"{number:g}"
    return prefix + text


def _payload(cell) -> dict:
    item: dict = {}
    value = cell.value
    text = _cell_text(value)
    numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
    if numeric:
        fmt = cell.number_format or "General"
        shown = _format_number(value, fmt)
        if shown != text:
            item["raw"] = text
        text = shown
        item["n"] = 1
    if text:
        item["v"] = text
    if isinstance(cell.value, str) and cell.value.startswith("="):
        item["f"] = cell.value
    style = {}
    if cell.font is not None:
        if cell.font.bold:
            style["b"] = 1
        if cell.font.italic:
            style["i"] = 1
        color = _argb(cell.font.color)
        if color:
            style["fg"] = color
        size = cell.font.sz
        if size and abs(float(size) - 11.0) > 0.01:
            style["fs"] = round(float(size), 1)
    if cell.alignment is not None:
        align = cell.alignment.horizontal
        if align in ("left", "center", "right"):
            style["a"] = align
        if cell.alignment.vertical in ("top", "center", "bottom"):
            style["va"] = cell.alignment.vertical
        if cell.alignment.wrap_text:
            style["wrap"] = 1
    bg = _fill(cell)
    if bg:
        style["bg"] = bg
    if style:
        item["s"] = style
    return item


def grid(path: Path, max_rows: int = MAX_ROWS, max_cols: int = MAX_COLS) -> dict:
    """读取工作簿为二维网格；公式同时返回缓存值与公式原文。"""
    wb = load_workbook(str(path), data_only=False, read_only=False)
    cached = None
    try:
        cached = load_workbook(str(path), data_only=True, read_only=False)
    except Exception:
        cached = None
    try:
        sheets = []
        for ws in wb.worksheets:
            total_rows = min(int(ws.max_row or 1), max(1, max_rows))
            total_cols = min(int(ws.max_column or 1), max(1, max_cols))
            rows = []
            cached_ws = cached[ws.title] if cached is not None and ws.title in cached.sheetnames else None
            for r in range(1, total_rows + 1):
                row = []
                for c in range(1, total_cols + 1):
                    cell = ws.cell(row=r, column=c)
                    item = _payload(cell)
                    if item.get("f") and cached_ws is not None:
                        cached_cell = cached_ws.cell(row=r, column=c)
                        if cached_cell.value is not None:
                            shown = _payload(cached_cell)
                            item["v"] = shown.get("v", "")
                            if shown.get("raw"):
                                item["raw"] = shown["raw"]
                            if shown.get("n"):
                                item["n"] = 1
                    row.append(item if item else None)
                rows.append(row)
            widths = {}
            for key, dim in (ws.column_dimensions or {}).items():
                if dim.width:
                    widths[key] = round(min(float(dim.width) * 7.6, 320), 1)
            merges = []
            for rng in list(ws.merged_cells.ranges)[:80]:
                merges.append(str(rng))
            sheets.append({
                "name": ws.title,
                "rows": rows,
                "rows_total": int(ws.max_row or 0),
                "cols_total": int(ws.max_column or 0),
                "widths": widths,
                "merges": merges,
                "truncated": int(ws.max_row or 0) > total_rows or int(ws.max_column or 0) > total_cols,
            })
        return {"ok": True, "sheets": sheets, "active": wb.active.title if wb.active else sheets[0]["name"]}
    finally:
        wb.close()
        if cached is not None:
            cached.close()


def _sheet_paths(zf: zipfile.ZipFile) -> dict[str, str]:
    """工作表名 -> 包内 worksheet XML 路径。"""
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.get("Id"): rel.get("Target") for rel in rels}
    out = {}
    for sheet in workbook.findall(f"{{{NS}}}sheets/{{{NS}}}sheet"):
        rid = sheet.get(f"{{{REL_NS}}}id")
        target = rel_map.get(rid) or ""
        if not target:
            continue
        if target.startswith("/"):
            full = target.lstrip("/")
        else:
            full = posixpath.normpath(posixpath.join("xl", target))
        out[sheet.get("name") or ""] = full
    return out


def _set_cell(row_el: ET.Element, ref: str, value: str) -> None:
    col = re.match(r"([A-Za-z]+)", ref)
    col_idx = _col_index(col.group(1) if col else "A")
    cell = None
    for candidate in row_el.findall(f"{{{NS}}}c"):
        if (candidate.get("r") or "").upper() == ref.upper():
            cell = candidate
            break
    if cell is None:
        cell = ET.Element(f"{{{NS}}}c", {"r": ref.upper()})
        inserted = False
        for idx, existing in enumerate(list(row_el.findall(f"{{{NS}}}c"))):
            match = re.match(r"([A-Za-z]+)", existing.get("r") or "A")
            if _col_index(match.group(1) if match else "A") > col_idx:
                row_el.insert(idx, cell)
                inserted = True
                break
        if not inserted:
            row_el.append(cell)
    for tag in ("v", "f", "is"):
        for child in cell.findall(f"{{{NS}}}{tag}"):
            cell.remove(child)
    text = str(value if value is not None else "")
    if text.startswith("="):
        cell.attrib.pop("t", None)
        formula = ET.SubElement(cell, f"{{{NS}}}f")
        formula.text = text[1:]
        return
    if text == "":
        cell.attrib.pop("t", None)
        return
    raw = text.strip()
    leading_zero = re.fullmatch(r"[-+]?0\d+", raw) is not None
    if re.fullmatch(r"[-+]?\d+", raw) and not leading_zero:
        cell.attrib.pop("t", None)
        ET.SubElement(cell, f"{{{NS}}}v").text = str(int(raw))
        return
    number = None
    try:
        if re.fullmatch(r"[-+]?(\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", raw) and not leading_zero:
            number = float(raw)
    except ValueError:
        number = None
    if number is not None:
        cell.attrib.pop("t", None)
        ET.SubElement(cell, f"{{{NS}}}v").text = ("%s" % number)
        return
    if text in ("TRUE", "FALSE"):
        cell.set("t", "b")
        ET.SubElement(cell, f"{{{NS}}}v").text = "1" if text == "TRUE" else "0"
        return
    cell.set("t", "inlineStr")
    inline = ET.SubElement(cell, f"{{{NS}}}is")
    node = ET.SubElement(inline, f"{{{NS}}}t")
    node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    node.text = text


def update_cells(path: Path, updates: list[dict]) -> dict:
    """按单元格写回值/公式；直接改 XML，避免丢失图表、图片与条件格式。"""
    if not updates:
        return {"ok": True, "updated": 0}
    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()
        payload = {name: zf.read(name) for name in names}
        sheet_paths = _sheet_paths(zf)
        grouped: dict[str, list[dict]] = {}
        for item in updates:
            sheet = str(item.get("sheet") or "")
            cell = str(item.get("cell") or "").upper()
            if not sheet or not re.fullmatch(r"[A-Z]+\d+", cell):
                continue
            grouped.setdefault(sheet, []).append({"cell": cell, "value": item.get("value", "")})
        if not grouped:
            return {"ok": False, "error": "没有有效的单元格更新"}
        changed = {}
        for sheet, items in grouped.items():
            xml_path = sheet_paths.get(sheet)
            if not xml_path or xml_path not in names:
                return {"ok": False, "error": f"找不到工作表：{sheet}"}
            root = ET.fromstring(payload[xml_path])
            sheet_data = root.find(f"{{{NS}}}sheetData")
            if sheet_data is None:
                sheet_data = ET.SubElement(root, f"{{{NS}}}sheetData")
            for item in items:
                ref = item["cell"]
                row_no = int(re.search(r"\d+", ref).group(0))
                row_el = None
                for candidate in sheet_data.findall(f"{{{NS}}}row"):
                    if int(candidate.get("r") or 0) == row_no:
                        row_el = candidate
                        break
                if row_el is None:
                    row_el = ET.Element(f"{{{NS}}}row", {"r": str(row_no)})
                    inserted = False
                    for idx, existing in enumerate(list(sheet_data.findall(f"{{{NS}}}row"))):
                        if int(existing.get("r") or 0) > row_no:
                            sheet_data.insert(idx, row_el)
                            inserted = True
                            break
                    if not inserted:
                        sheet_data.append(row_el)
                _set_cell(row_el, ref, item["value"])
            changed[xml_path] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        if "xl/workbook.xml" in payload:
            wb_root = ET.fromstring(payload["xl/workbook.xml"])
            calc = wb_root.find(f"{{{NS}}}calcPr")
            if calc is None:
                calc = ET.SubElement(wb_root, f"{{{NS}}}calcPr")
            calc.set("fullCalcOnLoad", "1")
            changed["xl/workbook.xml"] = ET.tostring(wb_root, encoding="utf-8", xml_declaration=True)
    fd, tmp_name = tempfile.mkstemp(suffix=".xlsx", dir=str(path.parent))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
            for name in names:
                data = changed.get(name)
                out.writestr(name, data if data is not None else payload[name])
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return {"ok": True, "updated": sum(len(v) for v in grouped.values())}


def _unique_sheet_name(base: str, existing: list[str]) -> str:
    base = re.sub(r"[\[\]:*?/\\]", "", str(base or "")).strip() or "Sheet"
    base = base[:31]
    if base not in existing:
        return base
    for i in range(2, 100):
        suffix = str(i)
        candidate = base[: 31 - len(suffix)] + suffix
        if candidate not in existing:
            return candidate
    return base[:28] + "100"


def add_sheet(path: Path, name: str = "") -> dict:
    """在 xlsx 末尾追加一张空工作表，保留原有图表/图片/样式。"""
    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()
        payload = {item: zf.read(item) for item in names}
    if "xl/workbook.xml" not in payload or "xl/_rels/workbook.xml.rels" not in payload:
        return {"ok": False, "error": "不是有效的 xlsx 文件"}
    wb_root = ET.fromstring(payload["xl/workbook.xml"])
    sheets_el = wb_root.find(f"{{{NS}}}sheets")
    if sheets_el is None:
        sheets_el = ET.SubElement(wb_root, f"{{{NS}}}sheets")
    existing_names = [s.get("name") or "" for s in sheets_el.findall(f"{{{NS}}}sheet")]
    new_name = _unique_sheet_name(name or f"Sheet{len(existing_names) + 1}", existing_names)
    sheet_id = max([int(s.get("sheetId") or 0) for s in sheets_el.findall(f"{{{NS}}}sheet")] or [0]) + 1
    rels_text = payload["xl/_rels/workbook.xml.rels"].decode("utf-8", "replace")
    used_rid = [int(x) for x in re.findall(r'Id="rId(\d+)"', rels_text)] or [0]
    rid = f"rId{max(used_rid) + 1}"
    numbers = []
    for item in names:
        match = re.fullmatch(r"xl/worksheets/sheet(\d+)\.xml", item)
        if match:
            numbers.append(int(match.group(1)))
    number = max(numbers or [0]) + 1
    ET.SubElement(sheets_el, f"{{{NS}}}sheet", {
        "name": new_name, "sheetId": str(sheet_id), f"{{{REL_NS}}}id": rid,
    })
    payload["xl/workbook.xml"] = ET.tostring(wb_root, encoding="utf-8", xml_declaration=True)
    rels_text = rels_text.replace(
        "</Relationships>",
        f'<Relationship Id="{rid}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{number}.xml"/></Relationships>')
    payload["xl/_rels/workbook.xml.rels"] = rels_text.encode("utf-8")
    if "[Content_Types].xml" in payload:
        content_types = payload["[Content_Types].xml"].decode("utf-8", "replace")
        content_types = content_types.replace(
            "</Types>",
            f'<Override PartName="/xl/worksheets/sheet{number}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>")
        payload["[Content_Types].xml"] = content_types.encode("utf-8")
    new_part = f"xl/worksheets/sheet{number}.xml"
    payload[new_part] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<worksheet xmlns="{NS}"><sheetData/></worksheet>').encode("utf-8")
    names.append(new_part)
    fd, tmp_name = tempfile.mkstemp(suffix=".xlsx", dir=str(path.parent))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
            for item in names:
                out.writestr(item, payload[item])
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return {"ok": True, "name": new_name, "sheets": len(existing_names) + 1}


def create(path: Path, sheets: list[dict], freeze_header: bool = True) -> dict:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    wb.remove(wb.active)
    head_fill = PatternFill("solid", fgColor="1F2937")
    head_font = Font(bold=True, color="FFFFFF", size=11)
    border = Border(bottom=Side(style="thin", color="D9DEE7"))
    for spec in sheets or []:
        name = str(spec.get("name") or f"Sheet{len(wb.sheetnames) + 1}")[:31]
        ws = wb.create_sheet(name)
        rows = spec.get("rows") or []
        for r, row in enumerate(rows, start=1):
            for c, value in enumerate(row or [], start=1):
                cell = ws.cell(row=r, column=c)
                if isinstance(value, str) and value.startswith("="):
                    cell.value = value
                elif value is None:
                    cell.value = None
                else:
                    cell.value = value
                if r == 1:
                    cell.fill = head_fill
                    cell.font = head_font
                    cell.alignment = Alignment(vertical="center")
                    cell.border = border
        for c in range(1, max((len(r or []) for r in rows), default=0) + 1):
            longest = 0
            for r in rows[:60]:
                if c <= len(r or []):
                    longest = max(longest, len(_cell_text(r[c - 1])))
            ws.column_dimensions[get_column_letter(c)].width = max(10, min(longest + 4, 42))
        if freeze_header and rows:
            ws.freeze_panes = "A2"
    if not wb.sheetnames:
        wb.create_sheet("Sheet1")
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
    return {"ok": True, "path": str(path), "sheets": wb.sheetnames}


def read(path: Path, sheet: str | None = None, max_rows: int = 60, max_cols: int = 24) -> dict:
    data = grid(path, max_rows=max_rows, max_cols=max_cols)
    if not data.get("ok"):
        return data
    sheets = data["sheets"]
    if sheet:
        sheets = [s for s in sheets if s["name"] == sheet] or sheets
    compact = []
    for s in sheets:
        rows = []
        formulas = []
        for ri, row in enumerate(s["rows"]):
            values = []
            for ci, cell in enumerate(row):
                if not cell:
                    values.append("")
                    continue
                values.append(cell.get("raw", cell.get("v", "")))
                if cell.get("f"):
                    formulas.append({"cell": get_column_letter(ci + 1) + str(ri + 1),
                                     "formula": cell["f"]})
            rows.append(values)
        compact.append({
            "name": s["name"],
            "rows": rows,
            "formulas": formulas[:120],
            "rows_total": s["rows_total"],
            "cols_total": s["cols_total"],
            "truncated": s["truncated"],
        })
    return {"ok": True, "sheets": compact}

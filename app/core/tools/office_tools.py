"""办公文档工具：读取、生成与编辑 PDF / Word / Excel / PowerPoint。"""
from __future__ import annotations

from pathlib import Path

from ..config import Config
from ..office import docx_doc, html2pptx, kind_of, pdf_doc, pptx_doc, xlsx_doc
from ..safety import Safety
from .registry import Registry, Tool

_SLIDE_DOC = "slides 每项支持 layout(cover/section/content/closing)、title、subtitle、bullets、" \
             "paragraphs、table(二维数组)、image(图片路径)、notes。"


def _file_result(path: Path, message: str, **extra) -> dict:
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    result = {"ok": True, "path": str(path), "name": path.name, "bytes": size, "output": message}
    result.update(extra)
    return result


def register(reg: Registry, config: Config, safety: Safety) -> None:
    def office_read(args: dict) -> dict:
        path = safety.resolve(args.get("path", ""), for_write=False)
        if not path.exists():
            return {"ok": False, "error": f"文件不存在：{path}"}
        kind = kind_of(path)
        if not kind:
            return {"ok": False, "error": "只支持 PDF / Word(docx) / Excel(xlsx) / PowerPoint(pptx)"}
        result = office_read_dispatch(path, kind, args)
        result["kind"] = kind
        result["path"] = str(path)
        return result

    def office_read_dispatch(path: Path, kind: str, args: dict) -> dict:
        if kind == "pdf":
            return pdf_doc.text(path, max_chars=int(args.get("max_chars") or 12000))
        if kind == "docx":
            return docx_doc.text(path, max_chars=int(args.get("max_chars") or 14000))
        if kind == "xlsx":
            return xlsx_doc.read(path, sheet=args.get("sheet"),
                                 max_rows=int(args.get("max_rows") or 60),
                                 max_cols=int(args.get("max_cols") or 24))
        return pptx_doc.read(path, max_chars=int(args.get("max_chars") or 12000))

    def _vetted_image(raw: str) -> str:
        return str(safety.resolve(raw, for_write=False))

    def docx_write(args: dict) -> dict:
        target = _target(args, "docx")
        blocks = args.get("blocks") or []
        if not isinstance(blocks, list) or not blocks:
            return {"ok": False, "error": "blocks 不能为空"}
        try:
            for block in blocks:
                if isinstance(block, dict) and str(block.get("type")) == "image" and block.get("path"):
                    block["path"] = _vetted_image(str(block["path"]))
        except PermissionError as e:
            return {"ok": False, "error": str(e)}
        docx_doc.create(target, str(args.get("title") or target.stem), blocks)
        return _file_result(target, f"已生成 Word 文档：{target.name}", blocks=len(blocks))

    def xlsx_write(args: dict) -> dict:
        target = _target(args, "xlsx")
        sheets = args.get("sheets") or []
        if not isinstance(sheets, list) or not sheets:
            return {"ok": False, "error": "sheets 不能为空"}
        for spec in sheets:
            if not isinstance(spec, dict) or not isinstance(spec.get("rows"), list):
                return {"ok": False, "error": "每个 sheet 需要 rows 二维数组"}
        xlsx_doc.create(target, sheets, freeze_header=bool(args.get("freeze_header", True)))
        return _file_result(target, f"已生成 Excel 工作簿：{target.name}", sheets=len(sheets))

    def pptx_write(args: dict) -> dict:
        target = _target(args, "pptx")
        slides = args.get("slides") or []
        if not isinstance(slides, list) or not slides:
            return {"ok": False, "error": "slides 不能为空"}
        try:
            for spec in slides:
                if not isinstance(spec, dict):
                    continue
                if spec.get("image"):
                    spec["image"] = _vetted_image(str(spec["image"]))
                if isinstance(spec.get("images"), list):
                    spec["images"] = [_vetted_image(str(p)) for p in spec["images"] if p]
        except PermissionError as e:
            return {"ok": False, "error": str(e)}
        pptx_doc.create(target, slides, str(args.get("title") or target.stem))
        return _file_result(target, f"已生成演示文稿：{target.name}", slides=len(slides))

    def html_to_pptx(args: dict) -> dict:
        source = safety.resolve(args.get("html_path") or args.get("path") or "", for_write=False)
        if not source.is_file():
            return {"ok": False, "error": f"HTML 文件不存在：{source}"}
        target = _target(args, "pptx")
        result = html2pptx.convert(source, target, str(args.get("title") or ""),
                                    str(args.get("selector") or ""))
        if not result.get("ok"):
            return result
        return _file_result(target, f"已把 {source.name} 转成 {result.get('slides')} 页 PPT：{target.name}",
                            slides=result.get("slides"),
                            warnings=result.get("warnings") or [])

    def office_edit(args: dict) -> dict:
        path = safety.resolve(args.get("path", ""), for_write=True)
        if not path.exists():
            return {"ok": False, "error": f"文件不存在：{path}"}
        kind = kind_of(path)
        ops = args.get("ops") or []
        if not isinstance(ops, list) or not ops:
            return {"ok": False, "error": "ops 不能为空"}
        if kind == "docx":
            updates = [{"index": op.get("index"), "text": op.get("text", "")}
                       for op in ops if str(op.get("kind") or "docx_text") == "docx_text"]
            if not updates:
                return {"ok": False, "error": "Word 只支持 kind=docx_text 的段落文本修改"}
            out = docx_doc.update_paragraphs(path, updates)
        elif kind == "xlsx":
            updates = [{"sheet": op.get("sheet"), "cell": op.get("cell"), "value": op.get("value", "")}
                       for op in ops if str(op.get("kind") or "xlsx_cell") == "xlsx_cell"]
            if not updates:
                return {"ok": False, "error": "Excel 只支持 kind=xlsx_cell 的单元格修改"}
            out = xlsx_doc.update_cells(path, updates)
        elif kind == "pptx":
            updates = [{"slide": op.get("slide"), "shape": op.get("shape"), "text": op.get("text", "")}
                       for op in ops if str(op.get("kind") or "pptx_text") == "pptx_text"]
            appended = []
            for op in ops:
                if str(op.get("kind")) == "pptx_append":
                    appended = op.get("slides") or []
            if not updates and not appended:
                return {"ok": False, "error": "PowerPoint 支持 pptx_text 改字或 pptx_append 追加页面"}
            out = pptx_doc.update_texts(path, updates) if updates else {"ok": True, "updated": 0}
            if appended:
                extra = pptx_doc.append(path, appended)
                if not extra.get("ok"):
                    return extra
                out["appended"] = extra.get("appended", len(appended))
        else:
            return {"ok": False, "error": "不支持的办公文件类型"}
        if not out.get("ok"):
            return out
        return _file_result(path, f"已更新 {path.name}", updated=out.get("updated", 0),
                            appended=out.get("appended", 0))

    def _target(args: dict, suffix: str) -> Path:
        raw = str(args.get("path") or "").strip()
        if not raw:
            raw = "nexus-output." + suffix
        target = safety.resolve(raw, for_write=True)
        if target.suffix.lower() != "." + suffix:
            target = target.with_suffix("." + suffix)
        return target

    reg.add(Tool(
        name="office_read",
        description=(
            "读取 PDF / Word(docx) / Excel(xlsx) / PowerPoint(pptx) 的内容："
            "PDF 按页返回文本，Word 返回段落与表格文本（blocks 带段落 index），"
            "Excel 返回各表二维数据，PPT 返回每页文字（shapes 带形状 index）。"
            "大文件会截断并标记 truncated。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件绝对路径"},
                "sheet": {"type": "string", "description": "Excel 工作表名，默认全部"},
                "max_rows": {"type": "integer", "description": "Excel 每个表最多返回行数，默认 60"},
                "max_chars": {"type": "integer", "description": "PDF/Word/PPT 文本上限"},
            },
            "required": ["path"],
        },
        handler=office_read,
        tag="office",
    ))
    reg.add(Tool(
        name="docx_write",
        description=(
            "生成 Word 文档（.docx）。blocks 是内容块数组，按顺序写入："
            "heading(需 level 1-3)、paragraph、bullet(多行)、number(多行)、quote、"
            "table(rows 二维数组)、image(path 与可选 width 英寸)、page_break。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "输出 .docx 路径"},
                "title": {"type": "string", "description": "文档标题（写在首页顶部）"},
                "blocks": {
                    "type": "array",
                    "description": "内容块数组",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "text": {"type": "string"},
                            "level": {"type": "integer"},
                            "rows": {"type": "array", "items": {"type": "array", "items": {}}},
                            "path": {"type": "string"},
                            "width": {"type": "number"},
                        },
                    },
                },
            },
            "required": ["path", "blocks"],
        },
        handler=docx_write,
        tag="office",
    ))
    reg.add(Tool(
        name="xlsx_write",
        description=(
            "生成 Excel 工作簿（.xlsx）。sheets 每项包含 name 与 rows 二维数组；"
            "第一行按表头加粗并冻结；字符串以 = 开头会写成公式。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "输出 .xlsx 路径"},
                "sheets": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "rows": {"type": "array", "items": {"type": "array", "items": {}}},
                        },
                        "required": ["rows"],
                    },
                },
                "freeze_header": {"type": "boolean", "description": "是否冻结首行，默认是"},
            },
            "required": ["path", "sheets"],
        },
        handler=xlsx_write,
        tag="office",
    ))
    reg.add(Tool(
        name="pptx_write",
        description="生成 PowerPoint（.pptx，16:9 原生可编辑对象）。" + _SLIDE_DOC +
                    " image 可用本地绝对路径。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "输出 .pptx 路径"},
                "title": {"type": "string", "description": "演示文稿标题"},
                "slides": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "layout": {"type": "string"},
                            "title": {"type": "string"},
                            "subtitle": {"type": "string"},
                            "bullets": {"type": "array", "items": {"type": "string"}},
                            "paragraphs": {"type": "array", "items": {"type": "string"}},
                            "table": {"type": "array", "items": {"type": "array", "items": {}}},
                            "image": {"type": "string"},
                            "notes": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["path", "slides"],
        },
        handler=pptx_write,
        tag="office",
    ))
    reg.add(Tool(
        name="html_to_pptx",
        description=(
            "把 HTML 文件里的每一页转成一张 PPT（原生可编辑文本/表格/图片，不是截图）。"
            "推荐先用 fs_write 生成 HTML：每页写成 <section class=\"slide\">，"
            "封面加 class=\"cover\"，结尾加 class=\"closing\"；页内用 h1/h2 作标题、"
            "li 作要点、p 作正文、table 作表格、img 作配图。CSS 的背景色、文字色、"
            "强调色会被继承。可选 selector 指定自定义的页容器选择器。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "html_path": {"type": "string", "description": "源 HTML 绝对路径"},
                "path": {"type": "string", "description": "输出 .pptx 路径"},
                "title": {"type": "string", "description": "演示文稿标题，默认取 HTML title"},
                "selector": {"type": "string", "description": "自定义页容器 CSS 选择器"},
            },
            "required": ["html_path", "path"],
        },
        handler=html_to_pptx,
        tag="office",
    ))
    reg.add(Tool(
        name="office_edit",
        description=(
            "编辑已有的办公文件（会保留原格式）。ops 支持："
            "docx_text{index,text} 改 Word 第 index 个段落（index 来自 office_read 的 blocks）；"
            "xlsx_cell{sheet,cell,value} 改单元格，value 以 = 开头写成公式；"
            "pptx_text{slide,shape,text} 改某页某个文本形状（slide 从 1 开始，shape 来自 office_read 的 shapes）；"
            "pptx_append{slides:[...]} 追加新页（结构同 pptx_write）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要编辑的文件路径"},
                "ops": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string"},
                            "index": {"type": "integer"},
                            "text": {"type": "string"},
                            "sheet": {"type": "string"},
                            "cell": {"type": "string"},
                            "value": {},
                            "slide": {"type": "integer"},
                            "shape": {"type": "integer"},
                            "slides": {"type": "array", "items": {"type": "object"}},
                        },
                    },
                },
            },
            "required": ["path", "ops"],
        },
        handler=office_edit,
        tag="office",
    ))

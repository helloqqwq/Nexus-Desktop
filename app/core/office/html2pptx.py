"""把一页页 HTML 转成原生可编辑的 PPT。

每个 ``<section class="slide">``（或 .slide / [data-slide]）对应一张幻灯片：
提取标题、副标题、列表、段落、表格与图片，按内容自动选择版式，并用
python-pptx 生成真正的文本/表格/图片对象（不是整页截图）。
"""
from __future__ import annotations

import base64
import io
import re
from pathlib import Path

from bs4 import BeautifulSoup

from . import pptx_doc

_SKIP_CLASS = re.compile(r"(nav|footer|header|pagination|page-?num|progress|controls?|hint)", re.I)
_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)")
_TITLE_CLASS = re.compile(r"(title|heading|headline)", re.I)
_SUB_CLASS = re.compile(r"(subtitle|sub-title|lead|desc|tagline|caption)", re.I)


def _clean(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _color(value: str) -> str:
    value = str(value or "").strip()
    match = _COLOR_RE.search(value)
    if not match:
        return ""
    token = match.group(0)
    if token.startswith("#"):
        return token[:7].lower() if len(token) >= 7 else token.lower()
    nums = re.findall(r"[\d.]+", token)
    if len(nums) >= 3:
        try:
            return "#%02x%02x%02x" % (int(float(nums[0])), int(float(nums[1])), int(float(nums[2])))
        except ValueError:
            return ""
    return ""


def _decls(text: str) -> dict:
    out = {}
    for part in str(text or "").split(";"):
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        out[key.strip().lower()] = value.strip()
    return out


def _rules(soup: BeautifulSoup) -> list[tuple[str, dict]]:
    out = []
    for style in soup.find_all("style"):
        text = style.string or style.get_text() or ""
        for match in re.finditer(r"([^{}]+)\{([^{}]+)\}", text):
            selector = match.group(1).strip()
            if selector.startswith("@"):
                continue
            decls = _decls(match.group(2))
            if decls:
                out.append((selector, decls))
    return out


def _style(node, soup, rules, prop: str) -> str:
    value = _decls(node.get("style") or "").get(prop, "")
    if value:
        return value
    for selector, decls in rules:
        try:
            matched = soup.select(selector)
        except Exception:
            continue
        if node in matched and prop in decls:
            value = decls[prop]
    return value


def _skip(node) -> bool:
    for parent in [node] + list(node.parents)[:2]:
        if not getattr(parent, "attrs", None):
            continue
        marker = " ".join(str(parent.get("class") or "").split()) + " " + str(parent.get("id") or "")
        if marker.strip() and _SKIP_CLASS.search(marker):
            return True
    return False


def _slide_nodes(soup: BeautifulSoup) -> list:
    for selector in ("section.slide", ".slide", "[data-slide]", "section"):
        found = [n for n in soup.select(selector) if not _skip(n)]
        if found:
            top = [n for n in found if not any(p in found for p in n.parents)]
            return top or found
    body = soup.body or soup
    return [body]


def _image_src(node, base: Path, warnings: list[str]):
    src = str(node.get("src") or "").strip()
    if not src:
        return None
    if src.startswith("data:image/"):
        match = re.match(r"data:image/([a-zA-Z0-9+.-]+);base64,(.*)", src, re.S)
        if not match:
            return None
        try:
            raw = base64.b64decode(match.group(2))
        except Exception:
            return None
        return io.BytesIO(raw)
    if re.match(r"https?://", src, re.I) or src.lower().endswith(".svg"):
        warnings.append(f"跳过远程或 SVG 图片：{src[:80]}")
        return None
    if src.startswith("file:///"):
        src = src[8:]
    target = Path(src)
    if not target.is_absolute():
        target = (base / src).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        warnings.append(f"跳过 HTML 目录之外的图片：{src[:80]}")
        return None
    if target.is_file():
        return str(target)
    warnings.append(f"图片不存在：{src[:80]}")
    return None


def _one_slide(node, index: int, total: int, soup, rules, base: Path, warnings: list[str]) -> dict:
    title = ""
    title_node = None
    for candidate in node.find_all(["h1", "h2", "h3", "h4"]):
        if _clean(candidate.get_text()):
            title, title_node = _clean(candidate.get_text()), candidate
            break
    if not title:
        for candidate in node.find_all(True, class_=True):
            if _TITLE_CLASS.search(" ".join(candidate.get("class") or [])) and _clean(candidate.get_text()):
                title, title_node = _clean(candidate.get_text())[:120], candidate
                break

    subtitle = ""
    for candidate in node.find_all(True, class_=True):
        if _SUB_CLASS.search(" ".join(candidate.get("class") or [])) and _clean(candidate.get_text()):
            subtitle = _clean(candidate.get_text())[:240]
            break

    bullets = []
    for li in node.find_all("li"):
        text = _clean(li.get_text())
        if text and not _skip(li):
            bullets.append(text[:300])
    bullets = bullets[:10]

    paragraphs = []
    for p in node.find_all(["p", "blockquote"]):
        if _skip(p):
            continue
        text = _clean(p.get_text())
        if not text or text == subtitle:
            continue
        if re.fullmatch(r"\d+\s*(/\s*\d+)?", text):
            continue
        paragraphs.append(text[:400])
    paragraphs = paragraphs[:8]

    table_rows = []
    table = node.find("table")
    if table:
        for tr in table.find_all("tr"):
            cells = [_clean(c.get_text()) for c in tr.find_all(["th", "td"])]
            if any(cells):
                table_rows.append(cells)
        table_rows = table_rows[:18]

    images = []
    for img in node.find_all("img"):
        src = _image_src(img, base, warnings)
        if src is not None:
            images.append(src)
            break

    bg = _color(_style(node, soup, rules, "background-color") or _style(node, soup, rules, "background"))
    fg = _color(_style(node, soup, rules, "color"))
    accent = ""
    for selector, decls in rules:
        for key, value in decls.items():
            if key in ("--accent", "--primary", "--brand") or "accent" in key:
                accent = _color(value) or accent
    if not accent and title_node is not None:
        accent = _color(_style(title_node, soup, rules, "color"))
    if not fg and title_node is not None and not bg:
        fg = ""
    classes = " ".join(node.get("class") or []).lower()
    layout = ""
    if re.search(r"(cover|title-slide|hero)", classes) or (index == 0 and not bullets and not table_rows and not images):
        layout = "cover"
    elif re.search(r"(section|divider|chapter)", classes):
        layout = "section"
    elif re.search(r"(closing|end|thanks|thank-you)", classes):
        layout = "closing"
    return {
        "layout": layout,
        "title": title or ("幻灯片 %d" % (index + 1)),
        "subtitle": subtitle,
        "bullets": bullets,
        "paragraphs": paragraphs,
        "table": table_rows or None,
        "images": images,
        "bg": bg,
        "fg": fg,
        "accent": accent,
    }


def convert(html_path: Path, out_path: Path, title: str = "", selector: str = "") -> dict:
    raw = html_path.read_bytes()
    text = ""
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    soup = BeautifulSoup(text, "html.parser")
    if selector:
        nodes = [n for n in soup.select(selector) if not _skip(n)]
    else:
        nodes = _slide_nodes(soup)
    if not nodes:
        return {"ok": False, "error": "HTML 里没有找到可转换的幻灯片内容"}
    rules = _rules(soup)
    warnings: list[str] = []
    specs = []
    for i, node in enumerate(nodes):
        spec = _one_slide(node, i, len(nodes), soup, rules, html_path.parent, warnings)
        if not any([spec["title"], spec["bullets"], spec["paragraphs"], spec["table"], spec["images"]]):
            continue
        specs.append(spec)
    if not specs:
        return {"ok": False, "error": "HTML 里没有可提取的文字或图片"}
    doc_title = title or _clean((soup.title.string if soup.title and soup.title.string else "")) or html_path.stem
    result = pptx_doc.create(out_path, specs, doc_title)
    result["slides"] = len(specs)
    result["source"] = str(html_path)
    if warnings:
        result["warnings"] = warnings[:6]
    return result

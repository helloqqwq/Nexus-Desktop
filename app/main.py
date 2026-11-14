"""Nexus 启动器：图形界面默认，--selftest 自检。"""
from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import __version__
from app.core import diag
from app.core.agent import Agent, offline_answer
from app.core.config import Config, ConfigError
from app.core.safety import Safety
from app.core.store import Store
from app.core.tools import build as build_registry

log = logging.getLogger("nexus")


def setup_logging(config: Config) -> None:
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    try:
        handler = RotatingFileHandler(config.log_dir / "nexus.log", maxBytes=1024 * 1024,
                                      backupCount=3, encoding="utf-8")
        handler.setFormatter(fmt)
        log.addHandler(handler)
    except OSError:
        pass
    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    console.setFormatter(fmt)
    log.addHandler(console)


def single_instance() -> bool:
    """返回 True 表示已有实例在运行。"""
    if sys.platform != "win32":
        return False
    try:
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\Nexus.Desktop.SingleInstance")
        if not handle:
            return False
        return ctypes.windll.kernel32.GetLastError() == 183
    except OSError:
        return False


def mini_pdf_bytes(text: str) -> bytes:
    """生成一页最小 PDF（Helvetica 文本），供自检读取，不依赖第三方 PDF 写入库。"""
    content = f"BT /F1 16 Tf 20 80 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 120] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("latin-1")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode("latin-1")
    return bytes(out)


def selftest(config: Config, store: Store, safety: Safety, registry) -> int:
    results: list[tuple[str, bool, str]] = []

    def check(name: str, fn):
        started = time.perf_counter()
        try:
            detail = fn() or ""
            results.append((name, True, str(detail)[:200]))
            print(f"PASS  {name}  {detail}  ({(time.perf_counter() - started) * 1000:.0f}ms)")
        except Exception as e:
            results.append((name, False, f"{type(e).__name__}: {e}"))
            print(f"FAIL  {name}  {type(e).__name__}: {e}")

    old_key = config.api_key

    def dpapi():
        config.set_api_key("selftest-key-dpapi")
        got = config.api_key
        assert got == "selftest-key-dpapi", "DPAPI 回读不一致"
        return "加密/解密一致"

    def db():
        sid = store.create_session("自检会话", "supervised")
        store.add_message(sid, "user", "ping")
        rows = store.messages(sid)
        assert rows and rows[-1]["content"] == "ping"
        store.delete_session(sid)
        return f"会话读写正常（{len(rows)} 条）"

    def provider_config():
        import shutil as _shutil

        from app.core import providers as _providers
        from app.core.config import Config as _Config

        tmp = config.output_dir / "_selftest_providers"
        _shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            cfg2 = _Config(tmp)
            items = _providers.catalog()
            assert len(items) == 9, f"厂商数量：{len(items)}"
            assert len({i["id"] for i in items}) == 9, "厂商 id 重复"
            assert all(i.get("models") for i in items if i["id"] != "custom"), "内置厂商缺少模型"
            cfg2.set_provider_key("kimi", "selftest-key-kimi")
            cfg2.save_provider("kimi", {"models": ["kimi-k3.1-pro"]})
            assert cfg2.provider_has_key("kimi")
            assert not cfg2.provider_has_key("qwen"), "Key 串到其他厂商"
            assert cfg2.api_key == "", "默认厂商不应拿到 Kimi 的 Key"
            cfg2.set_active("kimi", "kimi-k3.1-pro")
            assert cfg2.active_provider() == "kimi"
            assert cfg2.api_key == "selftest-key-kimi"
            cfg2.save_provider("custom", {
                "name": "本地网关", "kind": "anthropic",
                "base_url": "https://example.com/v1", "models": ["my-model"],
            })
            cfg2.set_provider_key("custom", "selftest-key-custom")
            cfg2.set_active("custom", "my-model")
            assert cfg2.provider_kind() == "anthropic"
            assert cfg2.provider_base_url() == "https://example.com/v1"
            assert cfg2.provider_name() == "本地网关"
            cfg2.set("llm.model", "my-legacy-model")
            cfg2.save()
            cfg3 = _Config(tmp)
            assert cfg3.active_model() == "my-legacy-model", cfg3.active_model()
            assert "my-legacy-model" in cfg3.provider_models(), cfg3.provider_models()
            dumped = cfg2.as_dict()
            assert "key" not in dumped["llm"]["providers"]["kimi"], "前端仍能拿到 Key"
            return "9 家目录、多 Key 隔离与自定义协议正常"
        finally:
            _shutil.rmtree(tmp, ignore_errors=True)

    def update_manifest():
        import tempfile as _tempfile

        from app.core.config import Config as _Config
        from app.core.updater import Updater, manifest_update, manifest_url

        base = "https://example.com"
        assert manifest_url(base) == "https://example.com/update.json"
        assert manifest_url(base + "/update.json") == "https://example.com/update.json"
        newer = manifest_update({
            "version": "0.2.0",
            "notes": "自检",
            "simulate": True,
            "installer": {
                "name": "Nexus-Setup-0.2.0.exe",
                "url": "Nexus-Setup-0.2.0.exe",
                "size": 10,
                "sha256": "A" * 64,
            },
        }, base, "0.1.0")
        assert newer["has_update"] and newer["latest"] == "0.2.0", newer
        assert newer["asset_url"] == "https://example.com/Nexus-Setup-0.2.0.exe"
        assert newer["digest"] == "sha256:" + "a" * 64
        assert newer["simulate"] is True
        assert not manifest_update({"version": "0.1.0"}, base, "0.1.0")["has_update"]
        missing = manifest_update({"version": "0.3.0"}, base, "0.1.0")
        assert not missing["ok"], "缺少安装包时应报错"
        insecure = manifest_update({
            "version": "0.3.0",
            "installer": {"name": "a.exe", "url": "http://example.com/a.exe"},
        }, base, "0.1.0")
        assert not insecure["ok"], "非 https 下载地址应拒绝"

        tmp = _tempfile.mkdtemp(prefix="nexus-upd-selftest-")
        try:
            cfg2 = _Config(tmp)
            cfg2.set("update.base_url", "")
            cfg2.set("update.repo", "")
            assert Updater(cfg2).enabled() is False
            cfg2.set("update.base_url", base)
            assert Updater(cfg2).enabled() is True
            cfg2.set("update.base_url", "")
            cfg2.set("update.repo", "owner/repo")
            assert Updater(cfg2).enabled() is True
        finally:
            import shutil as _shutil
            _shutil.rmtree(tmp, ignore_errors=True)
        return "清单解析、版本比较与更新源优先级正常"

    def crypto():
        box = config.box
        token = box.encrypt_text("加密自检-Nexus")
        assert token.startswith("enc:v1:")
        assert box.decrypt_text(token) == "加密自检-Nexus"
        raw_cfg = config.path.read_bytes()
        assert raw_cfg.startswith(b"NXCFG1"), "配置文件未加密"
        assert "加密自检".encode("utf-8") not in raw_cfg
        assert not (config.dir / "config.json").exists(), "明文 config.json 仍然存在"
        sid = store.create_session("加密自检会话", "supervised")
        store.add_message(sid, "user", "明文不应出现")
        row = store._conn.execute(
            "SELECT title FROM sessions WHERE id=?", (sid,)).fetchone()
        assert row and str(row["title"]).startswith("enc:v1:"), "会话标题未加密"
        row = store._conn.execute(
            "SELECT content FROM messages WHERE session_id=?", (sid,)).fetchone()
        assert row and str(row["content"]).startswith("enc:v1:"), "消息正文未加密"
        store.delete_session(sid)
        return "配置与历史字段均已加密"

    def fs():
        base = config.output_dir / "_selftest"
        base.mkdir(parents=True, exist_ok=True)
        target = base / "hello.txt"
        w = registry.dispatch("fs_write", {"path": str(target), "content": "第一行\n第二行\n"})
        assert w.get("ok"), w.get("error")
        r = registry.dispatch("fs_read", {"path": str(target)})
        assert "第二行" in r.get("content", ""), r.get("error")
        e = registry.dispatch("fs_edit", {"path": str(target), "old": "第二行", "new": "改过的行"})
        assert e.get("ok"), e.get("error")
        r2 = registry.dispatch("fs_read", {"path": str(target)})
        assert "改过的行" in r2.get("content", "")
        target.unlink(missing_ok=True)
        base.rmdir()
        return "写入/读取/编辑正常"

    def sysinfo():
        res = registry.dispatch("sys_info", {})
        assert res.get("ok"), res.get("error")
        return (res.get("output") or "").splitlines()[0]

    def procs():
        res = registry.dispatch("proc_list", {"limit": 3})
        assert res.get("ok"), res.get("error")
        return f"{len(res.get('items') or [])} 个进程"

    def ping():
        res = diag.net_ping("127.0.0.1", 1)
        assert res.get("ok"), res.get("error")
        assert res.get("received", 0) >= 1, res
        return "127.0.0.1 可达（收包统计一致）"

    def offline():
        answer = offline_answer("我上不了网", registry)
        assert len(answer) > 30
        return answer.splitlines()[0]

    def schemas():
        items = registry.schemas()
        assert len(items) >= 10, f"工具数量不足：{len(items)}"
        return f"{len(items)} 个工具"

    def ui_windows():
        res = registry.dispatch("ui_windows", {})
        assert res.get("ok"), res.get("error")
        items = res.get("items") or []
        assert items, "没有找到可见窗口（请在已登录的桌面会话中运行）"
        return f"{len(items)} 个可见窗口"

    def ui_tree():
        found = registry.dispatch("ui_windows", {})
        candidates = [i for i in (found.get("items") or []) if not i.get("blocked")]
        assert candidates, "没有可读取的普通窗口"
        last = ""
        for target in candidates[:4]:
            res = registry.dispatch("ui_tree", {
                "hwnd": target["hwnd"], "depth": 1, "max_nodes": 24,
            })
            if res.get("ok") and res.get("count"):
                return f"{target['title'][:16]}：{res['count']} 个元素"
            last = res.get("error") or "没有子元素"
        raise AssertionError(f"UI 树读取失败：{last}")

    def doc_file():
        base = config.output_dir / "_selftest"
        base.mkdir(parents=True, exist_ok=True)
        target = base / "note.md"
        try:
            content = "# Nexus 自检\n\n- 第一项\n- 第二项\n"
            res = registry.dispatch("fs_write", {"path": str(target), "content": content})
            assert res.get("ok"), res.get("error")
            text = target.read_text(encoding="utf-8")
            assert "# Nexus 自检" in text and "第二项" in text
            return "Markdown 文档写入/回读正常"
        finally:
            target.unlink(missing_ok=True)
            try:
                base.rmdir()
            except OSError:
                pass

    def office_files():
        base = config.output_dir / "_selftest"
        base.mkdir(parents=True, exist_ok=True)
        docx = base / "office.docx"
        xlsx = base / "office.xlsx"
        deck = base / "office.pptx"
        page = base / "deck.html"
        pdf = base / "office.pdf"
        try:
            res = registry.dispatch("docx_write", {
                "path": str(docx),
                "blocks": [{"type": "heading", "level": 1, "text": "自检标题"},
                           {"type": "paragraph", "text": "原始正文"}],
            })
            assert res.get("ok"), res.get("error")
            res = registry.dispatch("office_edit", {
                "path": str(docx), "ops": [{"kind": "docx_text", "index": 1, "text": "修改后的正文"}],
            })
            assert res.get("ok") and res.get("updated") == 1, res
            res = registry.dispatch("office_read", {"path": str(docx)})
            assert "修改后的正文" in res.get("content", ""), res

            res = registry.dispatch("xlsx_write", {
                "path": str(xlsx),
                "sheets": [{"name": "数据", "rows": [["名称", "数量"], ["苹果", 1]]}],
            })
            assert res.get("ok"), res.get("error")
            res = registry.dispatch("office_edit", {
                "path": str(xlsx),
                "ops": [{"kind": "xlsx_cell", "sheet": "数据", "cell": "B2", "value": "42"}],
            })
            assert res.get("ok") and res.get("updated") == 1, res
            res = registry.dispatch("office_read", {"path": str(xlsx)})
            rows = res["sheets"][0]["rows"]
            assert rows[1][1] == "42", rows

            from app.core.office import xlsx_doc as _xlsx
            added = _xlsx.add_sheet(xlsx, "测试表")
            assert added.get("ok"), added
            res = registry.dispatch("office_read", {"path": str(xlsx)})
            assert any(s["name"] == "测试表" for s in res["sheets"]), res["sheets"]

            res = registry.dispatch("pptx_write", {
                "path": str(deck),
                "slides": [{"layout": "cover", "title": "自检演示", "subtitle": "HTML 转 PPT"},
                           {"title": "第二页", "bullets": ["要点一"]}],
            })
            assert res.get("ok"), res.get("error")
            res = registry.dispatch("office_edit", {
                "path": str(deck),
                "ops": [{"kind": "pptx_append", "slides": [{"title": "追加页", "bullets": ["追加要点"]}]}],
            })
            assert res.get("ok") and res.get("appended") == 1, res
            res = registry.dispatch("office_read", {"path": str(deck)})
            assert res.get("slides") == 3, res
            assert "自检演示" in res["content"][0]["text"], res["content"][0]

            page.write_text(
                '<!DOCTYPE html><html><head><meta charset="utf-8"><title>HTML 演示</title>'
                '<style>.slide{background:#0f172a;color:#fff}</style></head><body>'
                '<section class="slide cover"><h1>HTML 演示</h1><p class="subtitle">两页</p></section>'
                '<section class="slide"><h2>要点</h2><ul><li>原生文本</li><li>可继续编辑</li></ul></section>'
                "</body></html>", encoding="utf-8")
            res = registry.dispatch("html_to_pptx", {"html_path": str(page), "path": str(deck)})
            if not res.get("ok"):
                raise AssertionError(res.get("error"))
            res = registry.dispatch("office_read", {"path": str(deck)})
            assert res.get("slides") == 2, res
            assert "原生文本" in res["content"][1]["text"], res["content"][1]

            from app.core.office import pdf_doc as _pdf_doc

            pdf.write_bytes(mini_pdf_bytes("Nexus PDF selftest"))
            res = registry.dispatch("office_read", {"path": str(pdf)})
            assert "Nexus PDF selftest" in res["content"][0]["text"], res
            meta = _pdf_doc.info(pdf)
            assert meta["pages"] == 1 and meta["width"] > 0, meta
            rendered = _pdf_doc.render_page(pdf, 0, 1.2)
            assert rendered.get("ok") and rendered["data_url"].startswith("data:image/png;base64,"), rendered
            return "Word/Excel/PPT 生成读取编辑、HTML 转 PPT、PDF 读取正常"
        finally:
            for item in (docx, xlsx, deck, page, pdf):
                item.unlink(missing_ok=True)
            try:
                base.rmdir()
            except OSError:
                pass

    def html_file():
        base = config.output_dir / "_selftest"
        base.mkdir(parents=True, exist_ok=True)
        target = base / "page.html"
        try:
            html = (
                '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
                "<title>Nexus 自检</title><style>body{font-family:sans-serif}</style></head>"
                "<body><h1>Nexus 自检</h1><script>document.body.dataset.ok='1'</script></body></html>"
            )
            res = registry.dispatch("fs_write", {"path": str(target), "content": html})
            assert res.get("ok"), res.get("error")
            text = target.read_text(encoding="utf-8")
            assert "<style>" in text and "<script>" in text, "CSS/JS 未内联"
            assert "http://" not in text and "https://" not in text, "引用了外部资源"
            return "单文件 HTML 内联且无外部依赖"
        finally:
            target.unlink(missing_ok=True)
            try:
                base.rmdir()
            except OSError:
                pass

    def risky_tools_removed():
        assert registry.get("net_fix") is None, "net_fix 仍在工具注册表中"
        assert not hasattr(diag, "run_fix"), "diag.run_fix 仍存在"
        assert registry.get("ui_act").needs_confirm, "ui_act 未要求确认"
        return "net_fix 已移除；UI 操作仍需确认"

    def history():
        sid = store.create_session("自检历史", "supervised")
        try:
            store.add_message(sid, "user", "history-check")
            store.add_tool_run(sid, "sys_info", {}, True, "ok", 12)
            store.add_file(sid, str(config.output_dir / "check.txt"), "check.txt", 3)
            sessions = store.list_sessions(50)
            assert any(s["id"] == sid for s in sessions), "会话列表缺少自检记录"
            assert any(f["session_id"] == sid for f in store.list_files(50)), "文件记录缺失"
            assert any(t["session_id"] == sid for t in store.list_tool_runs(50)), "工具记录缺失"
        finally:
            store.delete_session(sid)
        return "会话/文件/工具记录均可查询"

    def region_math():
        from app.core.region import normalize_region

        bounds = {"left": -1920, "top": 0, "width": 3840, "height": 1080}
        clamped = normalize_region(
            {"left": -2200, "top": -40, "right": 100, "bottom": 200}, bounds
        )
        assert clamped and clamped["left"] == -1920 and clamped["top"] == 0
        assert clamped["width"] == 2020 and clamped["height"] == 200
        flipped = normalize_region(
            {"left": 100, "top": 100, "right": 50, "bottom": 40}, bounds
        )
        assert flipped and flipped["width"] == 50 and flipped["height"] == 60
        assert normalize_region({"left": 10, "top": 10, "right": 12, "bottom": 12},
                                bounds) is None
        return "多屏裁剪/反向拖拽/最小尺寸正常"

    def confirm_guard():
        from app.core.agent import Agent

        old_mode = config.get("mode")
        sid = store.create_session("确认拦截", "supervised")
        try:
            config.set("mode", "supervised")
            agent = Agent(config, store, safety, registry)
            events = []
            msg = agent._exec_tool(
                sid,
                {"id": "call_confirm",
                 "function": {"name": "shell_run",
                              "arguments": '{"program":"ping","args":["-n","1","127.0.0.1"]}'}},
                events.append,
                lambda _req: False,
                None,
            )
            assert any(e.get("type") == "confirm_request" for e in events), "没有发出确认请求"
            assert not any(e.get("type") == "tool_end" and e.get("ok") for e in events)
            assert "取消" in msg.get("content", ""), "取消结果未回传给模型"
            return "取消确认后命令不会执行"
        finally:
            config.set("mode", old_mode or "supervised")
            store.delete_session(sid)

    def agent_chain():
        """用桩模型跑完整 Agent → 工具 → 文件链路，验证文档与单文件 HTML 生成。"""
        from app.core import llm as llm_mod
        from app.core.agent import Agent

        base = config.output_dir / "_selftest_agent"
        base.mkdir(parents=True, exist_ok=True)
        md = base / "report.md"
        html = base / "page.html"
        md_text = "# 验收报告\n\n- 文档生成链路正常\n- 内容可回读\n"
        html_text = (
            '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
            "<title>验收页</title><style>body{margin:0;font-family:sans-serif}</style></head>"
            "<body><h1>验收页</h1><script>document.title='ok'</script></body></html>"
        )
        sid = store.create_session("生成链路验收", "supervised")
        old_key = config.api_key
        original = llm_mod.LLMClient.chat
        config.set_api_key("selftest-key")

        def fake_chat(self, messages, tools=None, cancel=None, on_delta=None,
                      on_reasoning=None, on_retry=None):
            if any(m.get("role") == "tool" for m in messages[-3:]):
                return {"text": "两份文件已生成", "tool_calls": []}
            return {"text": "", "tool_calls": [
                {"id": "call_md", "function": {
                    "name": "fs_write",
                    "arguments": json.dumps({"path": str(md), "content": md_text},
                                            ensure_ascii=False)}},
                {"id": "call_html", "function": {
                    "name": "fs_write",
                    "arguments": json.dumps({"path": str(html), "content": html_text},
                                            ensure_ascii=False)}},
            ]}

        llm_mod.LLMClient.chat = fake_chat
        try:
            events = []
            Agent(config, store, safety, registry).run(sid, "生成验收文档和网页",
                                                       on_event=events.append)
            assert md.exists() and html.exists(), "文件未生成"
            assert "# 验收报告" in md.read_text(encoding="utf-8")
            page = html.read_text(encoding="utf-8")
            assert "<style>" in page and "<script>" in page
            assert "http://" not in page and "https://" not in page
            done = [e for e in events if e.get("type") == "tool_end" and e.get("ok")]
            assert len(done) == 2, f"工具完成事件数量异常：{len(done)}"
            assert any(f["session_id"] == sid for f in store.list_files(50)), "文件未入库"
            return "桩模型下文档/HTML 生成与入库正常"
        finally:
            llm_mod.LLMClient.chat = original
            config.set_api_key(old_key or "")
            store.delete_session(sid)
            md.unlink(missing_ok=True)
            html.unlink(missing_ok=True)
            try:
                base.rmdir()
            except OSError:
                pass

    def file_tools():
        base = config.output_dir / "_selftest_files"
        sub = base / "sub"
        sub.mkdir(parents=True, exist_ok=True)
        a = base / "a.md"
        b = sub / "b.md"
        a.write_text("Nexus 验收\n第二行\n", encoding="utf-8")
        b.write_text("普通内容\n", encoding="utf-8")
        try:
            glob = registry.dispatch("fs_glob", {"pattern": "**/*.md", "dir": str(base)})
            assert glob.get("ok") and glob.get("count") == 2, glob
            found = registry.dispatch("fs_search", {
                "pattern": r"Nexus|验收", "dir": str(base), "glob": "*.md",
                "regex": True, "context": 1,
            })
            assert found.get("ok") and found.get("count", 0) >= 1, found
            deleted = registry.dispatch("fs_delete", {"paths": [str(a)]})
            assert deleted.get("ok") and not a.exists(), deleted
            assert registry.get("fs_delete").needs_confirm
            return "glob/正则搜索/回收站删除正常"
        finally:
            for path in (a, b):
                path.unlink(missing_ok=True)
            try:
                sub.rmdir()
                base.rmdir()
            except OSError:
                pass

    def web_tools():
        assert registry.get("web_search") and registry.get("web_fetch")
        bad = registry.dispatch("web_fetch", {"url": "file:///C:/Windows/win.ini"})
        assert not bad.get("ok") and "http" in (bad.get("error") or "")
        return "联网工具已注册，URL 校验正常"

    def dns_parse():
        good = (
            "服务器:  UnKnown\nAddress:  fe80::1\n\n"
            "名称:    www.example.com\nAddresses:  2001:db8::1\n\t  93.184.216.34\n"
        )
        assert diag._dns_answers(good) == ["2001:db8::1", "93.184.216.34"], diag._dns_answers(good)
        bad = "服务器:  UnKnown\nAddress:  fe80::1\n"
        assert diag._dns_answers(bad) == [], diag._dns_answers(bad)
        nx = "名称:    no-such-host.invalid\n*** ... can't find ...\n"
        assert diag._dns_answers(nx) == [], diag._dns_answers(nx)
        return "DNS 服务器地址与应答地址已区分"

    def empty_queries():
        base = config.output_dir / "_selftest_empty"
        base.mkdir(parents=True, exist_ok=True)
        try:
            glob = registry.dispatch("fs_glob", {"pattern": "**/*.xyz", "dir": str(base)})
            assert glob.get("ok") and glob.get("empty") and glob.get("found") is False, glob
            assert glob.get("count") == 0 and not glob.get("error"), glob
            found = registry.dispatch("fs_search", {
                "pattern": "definitely-not-found", "dir": str(base),
            })
            assert found.get("ok") and found.get("empty") and found.get("found") is False, found
            assert found.get("count") == 0 and not found.get("error"), found
            return "零匹配：ok=true、empty=true、found=false"
        finally:
            base.rmdir()

    def read_truncation():
        base = config.output_dir / "_selftest_trunc"
        base.mkdir(parents=True, exist_ok=True)
        target = base / "many.txt"
        target.write_text("\n".join(f"line {i}" for i in range(6)) + "\n", encoding="utf-8")
        big = base / "big.txt"
        big.write_text("\n".join(f"Q{i:03d} " + "x" * 60 for i in range(500)) + "\n", encoding="utf-8")
        longline = base / "longline.txt"
        longline.write_text("y" * 5000, encoding="utf-8")
        one_line = base / "nonewline.txt"
        one_line.write_text("没有换行的内容", encoding="utf-8")
        try:
            res = registry.dispatch("fs_read", {"path": str(target), "limit": 2})
            assert res.get("truncated") and res.get("next_offset") == 2, res
            assert res.get("warning"), res
            line_res = registry.dispatch("fs_read", {"path": str(longline)})
            assert line_res.get("line_truncated") and line_res.get("truncated"), line_res
            assert "超过" in (line_res.get("warning") or ""), line_res
            assert line_res.get("next_offset") is None, line_res
            assert len(line_res.get("content", "")) <= 3000, len(line_res.get("content", ""))
            mid = registry.dispatch("fs_read", {
                "path": str(longline), "offset": 0, "char_offset": 1000,
            })
            assert mid.get("next_offset") is None and mid.get("next_char_offset") == 4000, mid
            tail = registry.dispatch("fs_read", {
                "path": str(longline), "offset": 0,
                "char_offset": line_res.get("next_char_offset") or 0,
            })
            assert len(tail.get("content", "")) == 2000, len(tail.get("content", ""))
            assert not tail.get("truncated"), tail
            no_eol = registry.dispatch("fs_read", {"path": str(one_line)})
            assert no_eol.get("line_ending") == "NONE", no_eol
            large = registry.dispatch("fs_read", {"path": str(big), "limit": 400})
            lines_out = large.get("content", "").splitlines()
            assert len(lines_out) <= 60, f"单次返回过多行：{len(lines_out)}"
            assert large.get("returned_lines") == len(lines_out), large
            assert large.get("next_offset") in (None, len(lines_out)), (
                f"next_offset 与实际返回不一致：{large.get('next_offset')} vs {len(lines_out)}")
            more = registry.dispatch("fs_read", {
                "path": str(big), "offset": large.get("next_offset") or 0, "limit": 1,
            })
            assert more.get("content", "").startswith(f"Q{len(lines_out):03d}"), more
            return "截断提示与实际内容一致"
        finally:
            target.unlink(missing_ok=True)
            big.unlink(missing_ok=True)
            longline.unlink(missing_ok=True)
            one_line.unlink(missing_ok=True)
            base.rmdir()

    def ipconfig_parse():
        text = (
            "Windows IP 配置\n\n"
            "以太网适配器 以太网:\n\n"
            "   连接特定的 DNS 后缀 . . . . . . . : \n"
            "   IPv4 地址 . . . . . . . . . . . . : 10.0.0.5(首选)\n"
            "   默认网关. . . . . . . . . . . . . : fe80::1%17\n"
            "                                       192.168.1.1\n"
            "   DHCP 已启用 . . . . . . . . . . . : 是\n"
            "   DNS 服务器  . . . . . . . . . . . : 192.168.1.1\n"
            "                                       fe80::1%17\n"
            "\n无线局域网适配器 WLAN:\n\n   媒体已断开\n"
        )
        summary = diag.ipconfig_summary(text)
        assert summary["ipv4"] == ["10.0.0.5"], summary["ipv4"]
        assert "192.168.1.1" in summary["gateway"], summary["gateway"]
        assert summary["dns"] == ["192.168.1.1", "fe80::1%17"], summary["dns"]
        assert summary["dhcp"] is True, summary["dhcp"]
        assert summary["disconnected"] is False, summary["disconnected"]
        assert summary["disconnected_adapters"] == ["无线局域网适配器 WLAN"], summary
        return "网关续行/DNS/DHCP/连接状态解析正确"

    def arp_limit():
        res = registry.dispatch("net_diag", {"action": "arp", "limit": 2})
        assert res.get("ok"), res.get("error")
        entries = res.get("entries") or []
        assert len(entries) <= 2, f"limit 未生效：{len(entries)}"
        assert res.get("total", 0) >= len(entries), res
        return f"ARP 共 {res.get('total', 0)} 条，limit 生效"

    def service_state():
        res = registry.dispatch("service_list", {"filter": "Dnscache", "limit": 3})
        items = res.get("services") or []
        assert items, res
        state = str(items[0].get("state") or "")
        assert state and not state[0].isdigit(), f"状态仍带枚举数字：{state}"
        assert isinstance(items[0].get("state_code"), int), items[0]
        return f"Dnscache 状态为 {state}"

    def os_name():
        info = diag.sys_info()["info"]
        os_text = info["os"]
        build = int(os_text.rsplit("(", 1)[-1].rstrip(")").split(".")[-1] or 0)
        if build >= 22000:
            assert "Windows 11" in os_text, os_text
        return os_text

    def read_binary_and_bounds():
        base = config.output_dir / "_selftest_bin"
        base.mkdir(parents=True, exist_ok=True)
        bin_file = base / "blob.bin"
        bin_file.write_bytes(b"\x00\x01ABC\xff\xfe")
        crlf = base / "crlf.txt"
        crlf.write_bytes("第一行\r\n第二行\r\n".encode("utf-8"))
        try:
            res = registry.dispatch("fs_read", {"path": str(bin_file)})
            assert res.get("binary") and not res.get("ok"), res
            text = registry.dispatch("fs_read", {"path": str(crlf)})
            assert text.get("line_ending") == "CRLF", text
            out = registry.dispatch("fs_read", {"path": str(crlf), "offset": 99})
            assert not out.get("ok") and out.get("hint"), out
            return "二进制拒绝、CRLF 标记、越界提示正常"
        finally:
            bin_file.unlink(missing_ok=True)
            crlf.unlink(missing_ok=True)
            base.rmdir()

    def sandbox_message():
        outside = Path(os.environ.get("SystemDrive", "C:") + "\\Windows\\win.ini")
        assert outside.exists(), f"找不到用于测试的系统文件：{outside}"
        read_res = registry.dispatch("fs_read", {"path": str(outside)})
        assert "允许读取的位置" in read_res.get("error", ""), read_res
        del_res = registry.dispatch("fs_delete", {"paths": [str(outside)]})
        assert "允许删除的位置" in del_res.get("error", ""), del_res
        assert outside.exists(), "测试文件不应被删除"
        return "读取/删除的沙箱提示已区分"

    def browser_urls():
        from app.ui import browser_target

        local = browser_target(__file__)
        assert local and local.startswith("file:///"), local
        assert browser_target("www.example.com") == "https://www.example.com"
        assert browser_target("localhost:5173") == "http://localhost:5173"
        assert browser_target("不是地址") is None
        return "网址/本地路径解析正常"

    def ping_unreachable():
        text = (
            "正在 Ping 192.168.1.250 具有 32 字节的数据:\n"
            "来自 192.168.1.40 的回复: 无法访问目标主机。\n"
            "来自 192.168.1.40 的回复: 无法访问目标主机。\n"
            "来自 192.168.1.40 的回复: 无法访问目标主机。\n"
            "来自 192.168.1.40 的回复: 无法访问目标主机。\n\n"
            "192.168.1.250 的 Ping 统计信息:\n"
            "    数据包: 已发送 = 4，已接收 = 4，丢失 = 0 (0% 丢失)，\n"
        )
        stats = diag._ping_counts(text, 4)
        assert stats["received"] == 0, stats
        assert stats["lost"] == 4, stats
        assert stats["icmp_errors"] == 4, stats
        return "ICMP 错误回复不计为可达"

    def route_limit():
        res = registry.dispatch("net_diag", {"action": "route", "limit": 3})
        assert res.get("ok"), res.get("error")
        total = int(res.get("total") or 0)
        assert len(res.get("entries") or []) <= max(3, total), res
        if total > 3:
            assert len(res["entries"]) == 3 and res.get("truncated"), res
            assert res.get("hint"), res
        return f"路由共 {total} 条，limit 生效"

    def ports_limit():
        res = registry.dispatch("net_diag", {"action": "ports", "limit": 3})
        assert res.get("ok"), res.get("error")
        rows = res.get("ports") or []
        total = int(res.get("total") or 0)
        assert len(rows) <= 3, len(rows)
        if total > len(rows):
            assert res.get("truncated") and res.get("hint"), res
        return f"监听端口共 {total} 条，limit 生效"

    def utf16_files():
        base = config.output_dir / "_selftest_utf16"
        base.mkdir(parents=True, exist_ok=True)
        target = base / "u16.txt"
        target.write_bytes("第一行\r\n第二行\r\n".encode("utf-16"))
        try:
            res = registry.dispatch("fs_read", {"path": str(target)})
            assert res.get("ok") and not res.get("binary"), res
            assert "第二行" in res.get("content", ""), res
            assert res.get("line_ending") == "CRLF", res
            found = registry.dispatch("fs_search", {
                "pattern": "第二行", "dir": str(base), "glob": "*.txt",
            })
            assert found.get("count") == 1, found
            edited = registry.dispatch("fs_edit", {
                "path": str(target), "old": "第二行", "new": "改过的行",
            })
            assert edited.get("ok") and edited.get("encoding") == "utf-16-le", edited
            again = registry.dispatch("fs_read", {"path": str(target)})
            assert "改过的行" in again.get("content", ""), again
            return "UTF-16 读取/检索/编辑正常"
        finally:
            target.unlink(missing_ok=True)
            base.rmdir()

    def glob_cap_note():
        from app.core.tools.fs_tools import _cap_note

        capped = _cap_note(300, 200)
        assert "单次最多返回 200 条" in capped, capped
        normal = _cap_note(100, 100)
        assert "调大 max_results" in normal, normal
        return "超过上限时不再建议调大 max_results"

    def write_denied():
        import stat

        base = config.output_dir / "_selftest_denied"
        base.mkdir(parents=True, exist_ok=True)
        target = base / "readonly.txt"
        target.write_text("原内容", encoding="utf-8")
        os.chmod(target, stat.S_IREAD)
        try:
            res = registry.dispatch("fs_write", {"path": str(target), "content": "新内容"})
            assert not res.get("ok") and res.get("denied"), res
            assert "权限" in (res.get("error") or ""), res
            assert res.get("hint"), res
            return res.get("error", "")[:24]
        finally:
            os.chmod(target, stat.S_IWRITE)
            target.unlink(missing_ok=True)
            base.rmdir()

    def control_release():
        from app.core.tools import desktop_tools

        tool = registry.get("release_control")
        assert tool is not None, "release_control 未注册"
        assert not tool.needs_confirm, "release_control 不应要求确认"
        idle = registry.dispatch("release_control", {})
        assert not idle.get("ok") and "接管" in (idle.get("error") or ""), idle
        called = []
        desktop_tools.set_control_release(lambda: called.append(1))
        try:
            ok = registry.dispatch("release_control", {})
            assert ok.get("ok") and called == [1], ok
        finally:
            desktop_tools.set_control_release(None)
        assert desktop_tools.KEY_MAP["backspace"] == "{Back}", desktop_tools.KEY_MAP["backspace"]
        return "交还控制权工具与按键映射正常"

    def runtime_modes():
        from app.core.prompts import build_system_prompt
        from app.core.tools import exclude_for

        old_mode = config.get("mode")
        try:
            config.set("mode", "safe")
            safe_prompt = build_system_prompt(config)
            assert "Current mode: Safe" in safe_prompt
            assert {"shell_exec", "shell_run", "fs_write", "app_launch"} <= exclude_for("safe")
            assert "fs_read" not in exclude_for("safe")

            config.set("mode", "supervised")
            supervised_prompt = build_system_prompt(config)
            assert "Current mode: Supervised" in supervised_prompt
            assert exclude_for("supervised") == set()

            config.set("mode", "full")
            full_prompt = build_system_prompt(config)
            assert "Current mode: Full access" in full_prompt
            assert exclude_for("full") == set()
            assert config.get("llm.thinking") in ("auto", "enabled", "disabled")
            return "三级权限模式：工具过滤与提示词正常"
        finally:
            config.set("mode", old_mode or "supervised")
            config.save()

    def prompt_style():
        from app.core.prompts import build_system_prompt

        text = build_system_prompt(config)
        banned = ("温暖", "亲切", "热情", "朋友", "哦", "呀", "！")
        hits = [word for word in banned if word in text]
        assert not hits, hits
        assert "Keep answers brief and factual" in text
        return "系统提示为简洁事实风格"

    def service_catalog():
        res = registry.dispatch("service_list", {"filter": "Dnscache", "limit": 10})
        assert res.get("ok") and res.get("total", 0) > 30, res
        names = [str(s.get("name", "")).lower() for s in res.get("services") or []]
        assert "dnscache" in names, res
        page = registry.dispatch("service_list", {"limit": 5})
        assert len(page.get("services") or []) == 5, page
        return f"完整枚举 {res['total']} 个服务，关键词可命中"

    def edit_newlines():
        base = config.output_dir / "_selftest_edit"
        base.mkdir(parents=True, exist_ok=True)
        p = base / "crlf.txt"
        q = base / "bom.txt"
        try:
            p.write_bytes("第一行\r\n第二行\r\n第三行\r\n".encode("utf-8"))
            res = registry.dispatch("fs_edit", {
                "path": str(p), "old": "第二行", "new": "第二行（改）"})
            assert res.get("ok"), res
            raw = p.read_bytes()
            assert b"\r\r\n" not in raw, raw[:120]
            assert raw == "第一行\r\n第二行（改）\r\n第三行\r\n".encode("utf-8"), raw
            q.write_bytes(b"\xef\xbb\xbfhello\r\nworld\r\n")
            res2 = registry.dispatch("fs_edit", {
                "path": str(q), "old": "world", "new": "Nexus"})
            assert res2.get("ok"), res2
            assert q.read_bytes() == b"\xef\xbb\xbfhello\r\nNexus\r\n", q.read_bytes()
            return "CRLF 与 BOM 原样保留"
        finally:
            for path in (p, q):
                path.unlink(missing_ok=True)
            try:
                base.rmdir()
            except OSError:
                pass

    def change_stats():
        """改动行数统计与“只取改动最大的 3 个文件”。"""
        base = config.output_dir / "_selftest_changes"
        base.mkdir(parents=True, exist_ok=True)
        p = base / "stats.txt"
        q = base / "overwrite.txt"
        try:
            p.write_bytes(b"a\nb\nc\n")
            res = registry.dispatch("fs_edit", {"path": str(p), "old": "b", "new": "b\nb2"})
            assert res.get("ok"), res
            assert (res.get("lines_added"), res.get("lines_removed")) == (1, 0), res
            q.write_bytes(b"l1\nl2\nl3\n")
            res2 = registry.dispatch("fs_write", {"path": str(q), "content": "l1\nl2\nl4\nl5\n"})
            assert res2.get("ok"), res2
            assert (res2.get("lines_added"), res2.get("lines_removed")) == (2, 1), res2

            from app.core.agent import Agent

            agent = Agent.__new__(Agent)
            agent._changes = {
                "/x/a": {"path": "/x/a", "name": "a", "added": 10, "removed": 1},
                "/x/b": {"path": "/x/b", "name": "b", "added": 5, "removed": 1},
                "/x/c": {"path": "/x/c", "name": "c", "added": 1, "removed": 1},
                "/x/d": {"path": "/x/d", "name": "d", "added": 3, "removed": 0},
            }
            seen = []
            agent._flush_changes(seen.append)
            evt = seen[0]
            assert evt["total"] == 4 and evt["more"] == 1, evt
            assert [i["name"] for i in evt["items"]] == ["a", "b", "d"], evt
            assert (evt["added"], evt["removed"]) == (19, 3), evt
            return "增删行数准确，只推送改动最大的 3 个"
        finally:
            for path in (p, q):
                path.unlink(missing_ok=True)
            try:
                base.rmdir()
            except OSError:
                pass

    def terminal_shells():
        """终端类型探测：至少提供 PowerShell / CMD，装了 Git Bash 时也能真正跑起来。"""
        from app.core.term import TerminalHub, shell_list

        items = shell_list()
        ids = [s["id"] for s in items]
        assert "powershell" in ids and "cmd" in ids, ids
        assert all(s.get("label") and s.get("badge") and s.get("argv") for s in items), items
        if "gitbash" not in ids:
            return "终端类型：" + "/".join(ids)

        events = []
        hub = TerminalHub(events.append)
        res = hub.start("gitbash", str(config.output_dir), 100, 24)
        assert res.get("ok"), res
        sid = res["id"]
        try:
            time.sleep(1.5)
            hub.write(sid, "echo NEXUS_GIT_OK\n")
            deadline = time.time() + 10
            text = ""
            while time.time() < deadline:
                time.sleep(0.4)
                text = "".join(e.get("data") or "" for e in events
                               if e.get("type") == "term_data")
                if "NEXUS_GIT_OK" in text:
                    break
            assert "NEXUS_GIT_OK" in text, text[-200:]
            return "终端类型：" + "/".join(ids)
        finally:
            hub.close(sid)
            assert hub.count() == 0

    def terminal_shell():
        """真实伪终端：能启动 PowerShell、写入命令、缩放并关闭。"""
        from app.core.term import TerminalHub

        events = []
        hub = TerminalHub(events.append)
        res = hub.start("powershell", str(config.output_dir), 100, 24)
        assert res.get("ok"), res
        sid = res["id"]
        try:
            deadline = time.time() + 10
            wrote = False
            text = ""
            while time.time() < deadline:
                if not wrote:
                    time.sleep(1.0)
                    hub.write(sid, "echo NEXUS_TERM_OK\r\n")
                    wrote = True
                else:
                    time.sleep(0.4)
                text = "".join(e.get("data") or "" for e in events
                               if e.get("type") == "term_data")
                if "NEXUS_TERM_OK" in text.replace("\r", ""):
                    break
            assert "NEXUS_TERM_OK" in text.replace("\r", ""), text[-200:]
            assert hub.resize(sid, 120, 30).get("ok")
            return "PowerShell 伪终端可启动、写入、缩放"
        finally:
            hub.close(sid)
            assert hub.count() == 0

    def tool_payload():
        from app.core.agent import _tool_content

        text = _tool_content({"ok": True, "output": "x" * 20000, "items": list(range(100))})
        assert len(text) <= 6000, len(text)
        obj = json.loads(text)
        assert obj.get("truncated") is True
        return "超长工具结果仍为合法 JSON"

    def long_task():
        """不设固定轮次上限：连续 10 轮工具调用后仍能正常收尾。"""
        from app.core import llm as llm_mod
        from app.core.agent import Agent

        sid = store.create_session("长任务自检", "supervised")
        old_key = config.api_key
        original = llm_mod.LLMClient.chat
        config.set_api_key("selftest-key")
        state = {"rounds": 0}

        def fake_chat(self, messages, tools=None, cancel=None, on_delta=None,
                      on_reasoning=None, on_retry=None):
            state["rounds"] += 1
            if state["rounds"] >= 11:
                return {"text": "长任务完成", "tool_calls": []}
            return {"text": "", "tool_calls": [{"id": f"call_{state['rounds']}", "function": {
                "name": "fs_list",
                "arguments": json.dumps({"dir": str(config.output_dir),
                                         "pattern": f"*.md{state['rounds']}"})}}]}

        llm_mod.LLMClient.chat = fake_chat
        try:
            events = []
            Agent(config, store, safety, registry).run(sid, "长任务自检",
                                                       on_event=events.append)
            assert state["rounds"] == 11, f"只跑了 {state['rounds']} 轮"
            assert not any(e.get("type") == "error" for e in events), events[-3:]
            assert any(e.get("type") == "assistant_done" and "完成" in (e.get("text") or "")
                       for e in events)
            return "连续 10 轮工具调用后正常收尾"
        finally:
            llm_mod.LLMClient.chat = original
            config.set_api_key(old_key or "")
            store.delete_session(sid)

    def assistant_profile():
        import base64
        import io

        from PIL import Image

        from app.core import avatar as avatar_store
        from app.core.prompts import build_system_prompt

        base = config.output_dir / "_selftest_avatar"
        base.mkdir(parents=True, exist_ok=True)
        old_name = config.get("ui.assistant_name")
        old_profile = config.get("ui.profile")
        try:
            buf = io.BytesIO()
            Image.new("RGB", (4, 4), (65, 118, 230)).save(buf, "PNG")
            data_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
            version = avatar_store.save(base, data_url)
            assert version > 0
            assert avatar_store.data_url(base).startswith("data:image/png;base64,")
            avatar_store.clear(base)
            assert avatar_store.data_url(base) == ""

            config.set("ui.assistant_name", "小N")
            profile = dict(old_profile or {})
            profile["name"] = "小林"
            config.set("ui.profile", profile)
            prompt = build_system_prompt(config)
            assert "小N" in prompt and "小林" in prompt
            return "头像裁切/清除与助手身份提示词正常"
        finally:
            config.set("ui.assistant_name", old_name or "Nexus")
            config.set("ui.profile", old_profile or {})
            avatar_store.clear(base)
            try:
                base.rmdir()
            except OSError:
                pass

    def scheduler_store():
        due_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 60))
        sid = store.add_schedule("自检定时任务", "检查网络", 0, due_time, once=1, session_id=7)
        try:
            items = store.list_schedules(10)
            row = next(i for i in items if i["id"] == sid)
            assert row["once"] == 1 and row["session_id"] == 7, row
            due = store.due_schedules(time.strftime("%Y-%m-%d %H:%M:%S"))
            assert any(i["id"] == sid for i in due)
            store.mark_schedule_run(sid, "", "自检完成")
            assert store.set_schedule_enabled(sid, False)
            assert not any(i["id"] == sid for i in store.due_schedules(
                time.strftime("%Y-%m-%d %H:%M:%S")))
            return "定时任务一次性/延时/到期查询正常"
        finally:
            store.delete_schedule(sid)

    print(f"\nNexus {__version__} 自检  |  数据目录：{config.dir}\n")
    check("配置加载", lambda: str(config.dir))
    check("DPAPI 密钥", dpapi)
    config.set_api_key(old_key or "")
    check("模型厂商配置", provider_config)
    check("更新清单解析", update_manifest)
    check("SQLite 历史", db)
    check("本地数据加密", crypto)
    check("文件工具沙箱", fs)
    check("文档生成（Markdown）", doc_file)
    check("单文件 HTML 生成", html_file)
    check("办公文档（Word/Excel/PPT/PDF）", office_files)
    check("系统信息", sysinfo)
    check("进程列表", procs)
    check("网络诊断", ping)
    check("离线排查", offline)
    check("工具注册表", schemas)
    check("电脑窗口枚举", ui_windows)
    check("UI 树读取", ui_tree)
    check("危险修复工具已移除", risky_tools_removed)
    check("历史记录查询", history)
    check("区域截图坐标", region_math)
    check("确认弹窗拦截", confirm_guard)
    check("Agent 生成链路（桩模型）", agent_chain)
    check("文件工具（glob/正则/删除）", file_tools)
    check("联网工具注册与校验", web_tools)
    check("DNS 应答解析", dns_parse)
    check("零匹配判定", empty_queries)
    check("读取截断提示", read_truncation)
    check("ipconfig 摘要解析", ipconfig_parse)
    check("ARP 条数限制", arp_limit)
    check("服务状态文本", service_state)
    check("系统版本命名", os_name)
    check("二进制与读取边界", read_binary_and_bounds)
    check("沙箱提示文案", sandbox_message)
    check("浏览器地址解析", browser_urls)
    check("ping 不可达判定", ping_unreachable)
    check("路由条数限制", route_limit)
    check("端口截断提示", ports_limit)
    check("UTF-16 文本", utf16_files)
    check("结果上限提示", glob_cap_note)
    check("写入权限文案", write_denied)
    check("控制权交还", control_release)
    check("运行时权限模式", runtime_modes)
    check("提示词事实风格", prompt_style)
    check("服务列表完整枚举", service_catalog)
    check("文件修改保留换行", edit_newlines)
    check("改动行数统计", change_stats)
    check("终端类型探测", terminal_shells)
    check("终端伪控制台", terminal_shell)
    check("工具结果合法截断", tool_payload)
    check("长任务连续执行", long_task)
    check("助手身份与头像", assistant_profile)
    check("定时任务数据层", scheduler_store)

    failed = [r for r in results if not r[1]]
    print(f"\n结果：{len(results) - len(failed)} 项通过，{len(failed)} 项失败")
    return 1 if failed else 0


def glow_preview() -> int:
    """只启动屏幕边缘光晕，用于单独观察/微调，按 ESC 退出。"""
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        pass

    from app.core.glow import ScreenGlow

    done = threading.Event()
    block = bool(os.environ.get("NEXUS_GLOW_BLOCK"))
    glow = ScreenGlow(done.set, block_input=block)
    glow.start()
    glow.show()
    print("光晕预览已启动，按 ESC 退出。" + ("（已屏蔽鼠标键盘）" if block else ""))
    try:
        while not done.wait(0.1):
            if not glow.alive():
                print("光晕线程已退出。")
                break
    except KeyboardInterrupt:
        pass
    finally:
        glow.close()
    return 0


def main() -> int:
    if "--pick-region" in sys.argv:
        # 框选子进程必须在创建任何窗口前开启 Per-Monitor DPI 感知，
        # 否则 Tk 坐标是逻辑像素，与物理截图之间会出现左上偏移。
        try:
            user32 = ctypes.windll.user32
            user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            pass
    parser = argparse.ArgumentParser(description="Nexus 桌面智能助手")
    parser.add_argument("--selftest", action="store_true", help="运行内核自检")
    parser.add_argument("--debug", action="store_true", help="显示调试信息")
    parser.add_argument("--pick-region", metavar="OUT", default=None,
                        help=argparse.SUPPRESS)
    parser.add_argument("--glow-preview", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.glow_preview:
        return glow_preview()

    if args.pick_region is not None:
        from app.core.region import pick_region

        picked = pick_region()
        payload = json.dumps(picked or {"cancelled": True}, ensure_ascii=False)
        try:
            Path(args.pick_region).write_text(payload, encoding="utf-8")
        except OSError:
            try:
                print(payload)
            except Exception:
                pass
        return 0

    try:
        config = Config()
    except ConfigError as e:
        print(f"启动失败：{e}")
        return 2
    setup_logging(config)
    if config.recovery_note and not args.selftest:
        try:
            user32 = ctypes.windll.user32
            user32.MessageBoxW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                           ctypes.c_wchar_p, ctypes.c_uint]
            user32.MessageBoxW(0, config.recovery_note, "Nexus", 0x00000040)
        except OSError:
            print(config.recovery_note)

    store = Store(config.db_path, config.box)
    safety = Safety(config, store)
    registry = build_registry(config, safety)

    if args.selftest:
        try:
            return selftest(config, store, safety, registry)
        finally:
            store.close()

    if single_instance():
        print("Nexus 已经在运行了（请查看桌面右下角）。")
        store.close()
        return 0

    try:
        from app.ui import launch
    except ImportError as e:
        print(f"图形界面组件不可用（{e}）。")
        return 4

    try:
        return launch(config, store, safety, registry, debug=args.debug)
    except Exception as e:
        log.exception("GUI 启动失败")
        print(f"图形界面启动失败：{e}")
        return 3
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())

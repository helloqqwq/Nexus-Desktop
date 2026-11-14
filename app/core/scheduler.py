"""轻量定时任务：只在图形界面进程存活时运行。"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

from .agent import Agent
from .config import Config
from .i18n import t
from .safety import Safety
from .store import Store
from .tools.registry import Registry, Tool

MIN_DELAY = 1
MAX_DELAY = 7 * 24 * 60
MIN_INTERVAL = 1
MAX_INTERVAL = 7 * 24 * 60


def _now() -> datetime:
    return datetime.now()


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _parse(text: str) -> datetime | None:
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


class Scheduler:
    def __init__(self, config: Config, store: Store, safety: Safety, registry: Registry):
        self.config = config
        self.store = store
        self.safety = safety
        self.registry = registry
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = threading.Lock()
        self._notify = None
        self.runner = None
        self.context_session_id: int | None = None

    def set_runner(self, runner) -> None:
        """由应用层注入：真正把 prompt 作为一条消息发给 AI 并回传界面。"""
        self.runner = runner

    def start(self, notify=None) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._notify = notify
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="nexus-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        time.sleep(3)
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                pass
            self._stop.wait(30)

    def _tick(self) -> None:
        if not self._running.acquire(blocking=False):
            return
        try:
            due = self.store.due_schedules(_fmt(_now()))
            for task in due:
                self._run_task(task)
        finally:
            self._running.release()

    def _run_task(self, task: dict) -> None:
        summary = ""
        if self.runner is not None:
            try:
                summary = str(self.runner(task) or "")
            except Exception as e:
                summary = f"定时任务执行失败：{e}"
        else:
            sid = self.store.create_session(f"定时：{task['title']}",
                                            str(self.config.get("mode") or "supervised"))
            events: list[dict] = []
            agent = Agent(self.config, self.store, self.safety, self.registry)
            cancel = threading.Event()
            try:
                agent.run(sid, str(task.get("prompt") or ""), on_event=events.append,
                          confirm=None, cancel=cancel, ask=None, notify=self._notify)
            except Exception as e:
                events.append({"type": "error", "message": f"定时任务执行失败：{e}"})
            for event in reversed(events):
                if event.get("type") == "assistant_done" and event.get("text"):
                    summary = str(event["text"])
                    break
        once = bool(task.get("once"))
        if once:
            self.store.mark_schedule_run(int(task["id"]), "", summary[:1000])
            self.store.set_schedule_enabled(int(task["id"]), False)
        else:
            interval = max(MIN_INTERVAL, int(task.get("interval_minutes") or MIN_INTERVAL))
            next_run = _now() + timedelta(minutes=interval)
            self.store.mark_schedule_run(int(task["id"]), _fmt(next_run), summary[:1000])
        if self._notify:
            try:
                self._notify(
                    t(f"定时任务完成：{task['title']}", f"Scheduled task finished: {task['title']}"),
                    (summary or t("已完成", "Completed"))[:200],
                )
            except Exception:
                pass


def register_tools(reg: Registry, scheduler: Scheduler) -> None:
    def schedule_task(args: dict) -> dict:
        title = str(args.get("title") or "").strip()[:80] or "定时任务"
        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            return {"ok": False, "error": "缺少 prompt"}
        try:
            delay = int(args.get("delay_minutes") or 0)
            interval = int(args.get("interval_minutes") or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "delay_minutes / interval_minutes 必须是整数"}
        if delay <= 0 and interval <= 0:
            return {"ok": False, "error": "需要 delay_minutes（一次性）或 interval_minutes（重复）"}
        once = delay > 0
        if once:
            if delay < MIN_DELAY or delay > MAX_DELAY:
                return {"ok": False,
                        "error": f"延时需在 {MIN_DELAY} 到 {MAX_DELAY} 分钟之间"}
            next_run = _fmt(_now() + timedelta(minutes=delay))
            minutes = 0
        else:
            if interval < MIN_INTERVAL or interval > MAX_INTERVAL:
                return {"ok": False,
                        "error": f"间隔需在 {MIN_INTERVAL} 到 {MAX_INTERVAL} 分钟之间"}
            next_run = _fmt(_now() + timedelta(minutes=interval))
            minutes = interval
        task_id = scheduler.store.add_schedule(
            title, prompt, minutes, next_run, once=1 if once else 0,
            session_id=scheduler.context_session_id)
        scheduler.safety.audit("schedule_task", {
            "id": task_id, "title": title, "once": once,
            "delay": delay if once else 0, "interval": minutes, "prompt": prompt[:300],
        })
        when = f"{delay} 分钟后一次性执行" if once else f"每 {minutes} 分钟重复"
        return {
            "ok": True, "id": task_id, "title": title, "prompt": prompt,
            "once": once, "delay_minutes": delay if once else 0,
            "interval_minutes": minutes, "next_run": next_run,
            "output": f"已安排定时任务 #{task_id}：{when}，下次 {next_run}。"
                      f"到点会把这段提示词发给 AI 自己执行：{prompt[:100]}",
        }

    def list_schedules(args: dict) -> dict:
        items = scheduler.store.list_schedules(50)
        lines = []
        for item in items:
            state = "启用" if item.get("enabled") else "已完成/暂停"
            when = (f"{item.get('next_run')} 一次性"
                    if item.get("once") else f"每 {item['interval_minutes']} 分钟")
            lines.append(
                f"#{item['id']} {item['title']} | {when} | {state} | "
                f"下次 {item.get('next_run') or '—'} | 上次 {item.get('last_run') or '未运行'}"
            )
        return {"ok": True, "items": items,
                "output": "\n".join(lines) or "还没有定时任务"}

    def cancel_schedule(args: dict) -> dict:
        try:
            sid = int(args.get("id") or 0)
        except (TypeError, ValueError):
            sid = 0
        if not sid:
            return {"ok": False, "error": "缺少 id"}
        if not scheduler.store.delete_schedule(sid):
            return {"ok": False, "error": f"没有找到定时任务 #{sid}"}
        scheduler.safety.audit("cancel_schedule", {"id": sid})
        return {"ok": True, "id": sid, "output": f"已取消定时任务 #{sid}"}

    reg.add(Tool(
        name="schedule_task",
        description=(
            "安排一个“到点提醒自己”的定时任务：时间到后，把 prompt 原样作为一条新消息发给 AI 自己执行。"
            "用户说“5 分钟后帮我写一个网页/整理一份资料”时使用 delay_minutes=5；"
            "prompt 必须自包含（写清背景、目标、产物路径、验收标准），不要写成给用户的提醒文案。"
            "例如：prompt='现在开始执行用户 5 分钟前提出的任务：做一个单文件 HTML 网页……完成后给出路径。' "
            "需要周期性重复时改用 interval_minutes。到点执行不会弹确认，只能使用不需要确认的工具。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "任务标题"},
                "prompt": {"type": "string",
                           "description": "到点发给 AI 自己的完整提示词（自包含，不要写成提醒用户的话）"},
                "delay_minutes": {"type": "integer",
                                  "description": f"多少分钟后一次性执行，{MIN_DELAY}-{MAX_DELAY}；与 interval_minutes 二选一"},
                "interval_minutes": {"type": "integer",
                                     "description": f"每隔多少分钟重复执行，{MIN_INTERVAL}-{MAX_INTERVAL}"},
            },
            "required": ["prompt"],
        },
        handler=schedule_task,
        needs_confirm=True,
        tag="schedule",
    ))
    reg.add(Tool(
        name="list_schedules",
        description="列出当前定时任务及下次运行时间。",
        parameters={"type": "object", "properties": {}},
        handler=list_schedules,
        tag="schedule",
    ))
    reg.add(Tool(
        name="cancel_schedule",
        description="取消一个定时任务，需要提供任务 id。",
        parameters={
            "type": "object",
            "properties": {"id": {"type": "integer", "description": "任务 id"}},
            "required": ["id"],
        },
        handler=cancel_schedule,
        tag="schedule",
    ))

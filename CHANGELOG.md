# 更新日志 · Changelog

Nexus Desktop 的版本更新记录。这里只列新增与改进的功能，不记录内部修复细节。

Release notes for Nexus Desktop. This file lists new features and improvements only.

---

## 0.2.0 — 2026-11-16

技能、系统提示词与长期记忆。

### 新增功能

- **技能（Skills）**：内置会议纪要、电脑排查、单页网页、周报四个技能。用输入框的 `/` 命令或 `+` 菜单选择，技能正文会随本轮对话一起发送；也可以把自己的 `SKILL.md` 或 `.json` 放进技能目录，刷新后即可使用。支持按描述自动匹配，或在设置里关闭自动匹配、只用 `/` 点名调用。
- **系统提示词库**：可以创建多条 Markdown 系统提示词，分别启用或停用，按名称顺序注入。编辑框左侧写 Markdown、右侧实时预览；名称留空时会根据正文自动取名。文件保存在 `prompts` 目录，也可以直接用外部编辑器修改。
- **长期记忆**：你明确说过的偏好、习惯和长期做法会被记住，并在之后的对话中自动带入。设置 → 记忆可以手动添加、编辑、删除或清空，内容加密保存在本机；模型只能写入你直接说过的内容。
- **更准确的上下文计量**：系统提示词、工具定义和真实 API 用量一起计入，缓存命中与缓存写入也纳入统计。输入框上方的占用环与实际请求一致，达到 50% 时自动压缩，也可以随时手动压缩。

### English

- **Skills**: four built-in skills (meeting notes, PC triage, single-page site, weekly report), invoked with `/` or the `+` menu. Add your own `SKILL.md` or `.json` to the skills folder, and optionally turn off automatic matching.
- **Prompt library**: multiple Markdown system prompts with per-item enable/disable, live preview while editing, and automatic naming when the name is left empty. Files live in the `prompts` folder and can be edited externally.
- **Long-term memory**: stable preferences you state are remembered and applied in later conversations. Memories can be viewed, edited, and deleted in Settings → Memory, and are stored encrypted on this machine.
- **Accurate context metering**: the system prompt, tool schemas, and real API usage (including cache reads and writes) are counted together. The context ring matches the actual request, auto-compresses at 50%, and can be compressed manually.

## 0.1.0 — 首个开源版本

首个开源版本：本地 AI 助手、电脑诊断、Office 文档、截图与语音输入、三级运行权限、本地数据加密与自动更新。

First open-source release: local AI assistant, PC diagnostics, Office documents, screenshots and voice input, three runtime permission levels, local data encryption, and auto-update.

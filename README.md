# Paper-Serch

Paper-Serch 是一个基于 Flask 的轻量级 Web 应用，用于快速检索文献并生成 BibTeX，支持可选的 AI 中文摘要与使用建议。

## 特性
- Web 端一站式完成检索、进度查看与 BibTeX 导出。
- 可选接入 Gemini 或 OpenAI 兼容接口生成中文摘要和引用提示。
- 表单预设示例检索式与默认年份/数量，开箱即用。
- 支持 SSE 实时推送运行状态（单次检索与自动工作流），方便排查问题。

## 环境与运行方式（使用 uv）
1. 创建虚拟环境并安装依赖：
   ```bash
   uv venv
   source .venv/bin/activate
   uv sync
   ```

2. 启动 Web 应用：
   ```bash
   uv run webapp.py
   ```
   默认监听 `http://127.0.0.1:5000`。

3. 关闭环境：
   ```bash
   deactivate
   ```

## 可选配置
在项目根目录创建 `.env`（可参考 `.env.example`），按需填写：
- `SECRET_KEY`（Flask session 签名密钥；建议生产环境设置）
- `PAPER_SERCH_DB_PATH`（SQLite 数据库路径；默认 `paper_serch.db`）
- `INITIAL_CREDITS`（注册默认赠送工作流次数；默认 3，管理员账号不消耗次数）
- `ALLOW_SELF_REGISTRATION`（是否开放自助注册；默认 `false`，管理员统一分配账号）
- `ADMIN_EMAIL` / `ADMIN_PASSWORD`（可选：启动时自动创建管理员账号）
- `PRESET_AI_PROVIDER`（默认 `openai`，普通用户使用的预设 Provider）
- `GEMINI_API_KEY` / `GEMINI_MODEL` / `GEMINI_TEMPERATURE`
- `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` / `OPENAI_TEMPERATURE`
- `PUBMED_MAX_CONCURRENT_REQUESTS`（默认 3，全局默认 PubMed 并发上限）
- `PUBMED_MAX_RETRIES` / `PUBMED_BACKOFF_BASE` / `PUBMED_BACKOFF_MAX`（PubMed 失败重试与退避）
- `AI_SUMMARY_CONCURRENCY`（AI 摘要并发；不设置/≤0 默认不限制）

未填写时可在 Web 表单中输入；缺省值会使用页面内置示例或后端默认值。

## 页面使用指南
1. 打开首页，选择文献来源（普通用户的 AI 配置自动读取预设，管理员可自由切换）。
2. 在“文献检索”区域填写检索式、时间范围与最大条数，或使用 AI 自动生成检索式预览后应用。
3. 需要 AI 摘要时，可直接使用预设模型；管理员可在页面填写模型与 API 参数。
4. 点击“开始检索”，右侧进度卡片会实时展示各步骤状态；批量拆解方向可在“自动工作流”页面进行。
5. 在结果区查看条目详情，展开摘要后复制或下载生成的 BibTeX。

## 管理员与权限
- 默认需要登录后使用；普通用户登录后仅可使用“自动工作流”，文献检索首页仅管理员可用。
- 默认关闭自助注册，可在 `.env` 中设置 `ADMIN_EMAIL/ADMIN_PASSWORD` 启动时自动创建管理员，或使用管理员面板 `/admin/users` 创建账号、调整余额/权限与配置用户使用的 AI（Provider/模型/API Key/Base URL）。
- 管理员账号不消耗次数；普通用户无法在页面修改 AI Provider、API Key 等敏感配置，将使用管理面板中为该用户设置的 AI 配置（留空则回退到 `.env` 的全局预设）。

## 目录速览
- `webapp.py`：入口脚本，导入并运行应用。
- `app/server.py`：Flask 应用与路由。
- `app/web/`：Web 层辅助模块（表单解析、SSE/流式检索封装）。
- `app/core/`：核心服务（DB、BibTeX、AI 查询/摘要等）。
- `app/sources/`：文献源实现与注册表。
- `app/ai/`：AI 提供方实现与注册表。
- `templates/`：页面模板。
- `static/`：样式与前端脚本。
- `docs/`：文档（数据库结构、提示词与当前不足）。

## 文档
- `docs/DATABASE.md`：数据库结构说明。
- `docs/AI_PROMPTS.md`：AI 提示词汇总。
- `docs/LIMITATIONS.md`：当前不足与改进建议。

## 开发提示
- 推荐使用 `uv run python -m compileall .` 做快速语法检查。
- 新增依赖请使用 `uv add <package>` 并提交更新后的 `pyproject.toml` 与 `uv.lock`。

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
- `INITIAL_CREDITS`（注册默认赠送工作流次数；默认 10）
- `GEMINI_API_KEY` / `GEMINI_MODEL` / `GEMINI_TEMPERATURE`
- `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` / `OPENAI_TEMPERATURE`
- `PUBMED_MAX_CONCURRENT_REQUESTS`（默认 3，全局默认 PubMed 并发上限）
- `PUBMED_MAX_RETRIES` / `PUBMED_BACKOFF_BASE` / `PUBMED_BACKOFF_MAX`（PubMed 失败重试与退避）
- `AI_SUMMARY_CONCURRENCY`（AI 摘要并发；不设置/≤0 默认不限制）

未填写时可在 Web 表单中输入；缺省值会使用页面内置示例或后端默认值。

## 页面使用指南
1. 打开首页，选择文献来源与 AI 模型（可选）。
2. 在“文献检索”区域填写检索式、时间范围与最大条数，或使用 AI 自动生成检索式预览后应用。
3. 需要 AI 摘要时，补全对应密钥与模型名称；留空将使用环境变量或默认值。
4. 点击“开始检索”，右侧进度卡片会实时展示各步骤状态；批量拆解方向可在“自动工作流”页面进行。
5. 在结果区查看条目详情，展开摘要后复制或下载生成的 BibTeX。

## 目录速览
- `webapp.py`：Flask 入口及 API。
- `web_layer/`：Web 层辅助模块（表单解析、SSE/流式检索封装）。
- `templates/`：页面模板（首页与新手教程）。
- `static/`：样式与前端脚本。
- `paper_sources/`：文献源实现与注册表。
- `ai_providers/`：AI 摘要提供方实现与注册表。
- `services/`：BibTeX 生成等通用服务。
- `docs/`：文档（变更记录、开发者说明、提示词与当前不足）。

## 文档
- `docs/CHANGELOG.md`：变更记录。
- `docs/DEVELOPER.md`：开发者指南。
- `docs/AI_PROMPTS.md`：AI 提示词汇总。
- `docs/LIMITATIONS.md`：当前不足与改进建议。

## 开发提示
- 推荐使用 `uv run python -m compileall .` 做快速语法检查。
- 新增依赖请使用 `uv add <package>` 并提交更新后的 `pyproject.toml` 与 `uv.lock`。

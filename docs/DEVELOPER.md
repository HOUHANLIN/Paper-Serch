# 开发者指南

本说明聚焦当前版本（0.5.0）的项目结构、常用运行方式与关键实现点。

## 本地开发（使用 uv）
1. 安装依赖：`uv venv && source .venv/bin/activate && uv sync`
2. 运行应用：`uv run webapp.py`，访问 `http://127.0.0.1:5000`
3. 语法检查：`python3 -m compileall .`

## 项目结构
- `webapp.py`：Flask 入口与路由（首页检索、自动工作流、下载等）。
- `web_layer/`：Web 层逻辑（表单解析、SSE 搜索封装）。
- `templates/`：Jinja2 页面模板（含 workflow 页面）。
- `static/`：前端脚本与样式（工作流请求、模型列表拉取、结果渲染）。
- `paper_sources/`：文献数据源（当前默认 PubMed）。
- `ai_providers/`：AI Provider（OpenAI/Gemini/Ollama）。
- `services/`：通用服务（方向拆解、检索式生成、AI 摘要、BibTeX 组装等）。
- `docs/`：项目文档（提示词、开发说明、不足与改进等）。

## 关键路由
- `POST /api/search_stream`：单次检索的 SSE 流（实时状态与最终结果）。
- `POST /api/auto_workflow_stream`：自动工作流 SSE（方向拆解 + 多方向并发检索，方向完成即推送结果）。
- `POST /api/list_models`：拉取 AI Provider 可用模型列表，填充到前端 datalist。

## 并发与限速（重要）

### 工作流并发
- 方向并发：当前默认不限制（方向越多线程越多）。
- PubMed 并发：由工作流页面“PubMed 并发”控制，并在一次 workflow 内用 semaphore 限制 PubMed HTTP 请求并发。

### AI 摘要并发
- `services/ai_summary.py` 会对每篇文章单独调用一次 summarize，并发数默认为“每篇文章一个并发 worker”（不限制）。
- 可通过环境变量 `AI_SUMMARY_CONCURRENCY` 覆盖并发上限（设置为正整数）。

### PubMed 重试与退避
PubMed 请求对 `429/5xx/超时/连接失败` 做了自动重试与指数退避，可通过环境变量配置：
- `PUBMED_MAX_RETRIES`（默认 `4`）
- `PUBMED_BACKOFF_BASE`（默认 `0.6`）
- `PUBMED_BACKOFF_MAX`（默认 `10`）

## 文档入口
- `docs/AI_PROMPTS.md`：项目内使用的 AI 提示词汇总（便于统一审阅）。
- `docs/LIMITATIONS.md`：当前不足与改进建议（迭代路线图的输入）。


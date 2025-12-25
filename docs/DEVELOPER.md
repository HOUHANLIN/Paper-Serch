# 开发者指南

本说明聚焦当前版本（0.5.0）的项目结构与本地开发方式，默认使用 `uv` 进行环境与依赖管理。

## 本地环境
1. 安装依赖：`uv venv && source .venv/bin/activate && uv sync`。
2. 运行应用：`uv run webapp.py`，访问 `http://127.0.0.1:5000`。
3. 快速检查：`uv run python -m compileall .` 可做语法级校验。

## 目录结构
- `webapp.py`：Flask 入口，包含 API 路由与 SSE 推送逻辑。
- `web_layer/`：Web 层拆分出的辅助逻辑（表单解析、流式检索、SSE 格式化）。
- `templates/`：Jinja2 模板，`index.html` 为首页，`tutorial.html` 为新手教程。
- `static/`：样式与前端脚本，`static/css/main.css` 定义统一配色与组件样式。
- `paper_sources/`：文献来源接口与实现，注册表统一暴露数据源。
- `ai_providers/`：AI 摘要提供方接口与实现，支持 Gemini、OpenAI 或关闭 AI。
- `services/`：通用服务层，包含 BibTeX 组装与辅助工具。
- `docs/`：文档与变更记录。

## 开发要点
- 依赖更新请通过 `uv add` 或 `uv remove`，并提交更新后的 `pyproject.toml` 与 `uv.lock`。
- 不使用 Docker；如需部署请基于常规 Python 环境，按 README 所述方式启动。
- 修改样式或模板时，保持与首页一致的配色与组件风格（`static/css/main.css` 中的变量为基准）。
- 新增文献源或 AI Provider 时，在对应 `registry.py` 中注册以供前端下拉列表使用。

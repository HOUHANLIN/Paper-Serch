# 版本更新记录（CHANGELOG）

本文件用于记录项目的版本更新历史，方便追踪功能演进和问题修复情况。约定如下：

- 按时间倒序记录版本（最新的在最上方）。
- 每个版本分为：日期、变更概述、详细内容。
- 版本号建议采用 `MAJOR.MINOR.PATCH` 格式，例如：`0.1.0`、`1.0.0` 等。

---

## v0.4.0: 实时进度与检索式预览

日期：2025-01-XX
状态：功能增强版本

**概述**

- Web 界面支持 SSE 流式进度，检索、AI 总结与 BibTeX 生成状态实时推送。
- AI 自动生成检索式增加预览与确认按钮，避免直接覆盖用户输入。
- PubMed 合规信息（邮箱/API Key）默认折叠，需要时再展开，首页文字更简洁。
- 文档同步更新，涵盖新界面行为和操作提示。

**详细内容**

- 后端：新增 `/api/search_stream`，使用生成器按步骤推送状态与结果；原有同步流程复用同一搜索逻辑。
- 前端：
  - 表单提交改为流式读取事件，状态列表即时刷新。
  - AI 生成检索式显示预览与“应用”按钮；BibTeX/文献列表动态更新。
  - 邮箱/API 输入默认隐藏，提供显式切换按钮；减少冗余提示文字。
- 文档：README、教程与开发文档补充了实时进度、检索式预览与折叠式合规信息的说明。

---

## v0.3.0: 插件化架构与多源/多模型预留

日期：2025-12-09
状态：功能增强版本

**概述**

- 将“文献数据源”和“AI 提供方”抽象为可注册的插件，便于后续接入其他站点与模型。
- Flask Web 界面与 CLI 流程统一通过注册表选择数据源和 AI，前端新增选择下拉框。
- 补充面向开发者的扩展说明，明确如何实现新的数据源或 AI Provider。

**详细内容**

- 新增：`paper_sources/` 与 `ai_providers/` 模块
  - 提供 `base.py` 协议/数据类定义，`registry.py` 管理注册表。
  - 内置 `PubMedSource` 与 `GeminiProvider`（自动检测配置）、`OpenAIProvider` 占位以及 `Noop` 选项。
- 业务逻辑调整
  - `webapp.py`：通过注册表驱动检索与 AI 总结，表单允许切换数据源和 AI 提供方。
  - `services/bibtex.py`：将 BibTeX 生成封装为可复用函数，便于不同数据源重用。
- 文档更新
  - README 与 DEVELOPER 文档补充插件化架构与扩展指引，版本标记为 `v0.3.0`。

---

## v0.2.1: 自动 Docker 构建

日期：2025-12-08  
状态：CI 配置更新

**概述**

- 为主分支与 Pull Request 增加自动 Docker 构建流程，确保每次提交的镜像都能成功构建。

**详细内容**

- 新增：`.github/workflows/docker-build.yml`
  - 在 `main` / `master` 分支 push 与 PR 时触发。
  - 使用 GitHub Actions + Docker Buildx 构建镜像：
    - `pubmed-bibtex:latest`
  - 当前仅在 CI 中构建，不默认推送到远程镜像仓库（后续可按需扩展 `docker push` 步骤）。

---

## v0.2.0: Web 前端与 Docker 支持

日期：2025-12-08  
状态：功能增强版本

**概述**

- 新增基于 Flask 的本地 Web 前端，可视化检索 PubMed 并查看精简结果。
- 新增 Docker 与 docker-compose 支持，一条命令即可在容器中运行 Web 版本。
- 优化 BibTeX 生成逻辑，支持前端展示结构化信息并一键导出 `.bib` 文件。

**详细内容**

- 新增：`webapp.py` + `templates/index.html`
  - 提供本地 Web 界面：
    - 表单方式输入检索式、年份范围、最大条数，可选邮箱与 NCBI API Key。
    - 调用现有检索与解析逻辑，复用 `pubmed_bibtex.py` 的核心能力。
  - 前端结果展示优化：
    - 新增“文献概览”列表，仅展示标题、作者、期刊/年份、摘要，以及 AI 总结（`summary_zh` + `usage_zh`）。
    - 若配置了 `GEMINI_API_KEY` 和 `GEMINI_MODEL`，会自动解析 `annote` 中的 JSON 并在页面中展示。
    - 保留原始 BibTeX 文本区域，支持复制到剪贴板。
  - 新增导出 BibTeX 功能：
    - `/download` 路由根据当前表单参数重新检索并生成 `.bib` 文件。
    - 通过 `Content-Disposition` 附件下载，文件名默认使用 `PUBMED_OUTPUT` 或 `pubmed_results.bib`。

- 优化：`pubmed_bibtex.py`
  - 抽取 `build_bibtex_entries()`：
    - 将 XML → BibTeX 的逻辑封装为可复用函数。
    - 返回 BibTeX 文本、条数以及每条文献的结构化 `info` 列表，便于 Web 前端消费。
  - `write_bibtex_file()` 复用上述函数，命令行行为保持不变。

- 新增：容器化与部署相关文件
  - `Dockerfile`
    - 基于 `python:3.11-slim` 构建运行环境。
    - 安装 `requirements.txt`，默认运行 Flask Web 前端（监听 `0.0.0.0:5000`）。
  - `docker-compose.yml`
    - 提供 `web` 服务：
      - `build: .`，映射宿主机 `5000` 端口。
      - 通过 `env_file: .env` 加载 PubMed 与 Gemini 配置。
      - 适合本地一键启动：`docker-compose up --build`。
  - `.dockerignore`
    - 忽略 `.git/`、`venv/`、`.env`、`.bib`、编辑器配置、构建产物等，减小镜像体积。

- 文档与依赖更新
  - `requirements.txt`：新增 `flask` 依赖。
  - `README.md`：
    - 新增 Web 前端与 Docker/docker-compose 使用说明。
    - 简化部分命令示例，突出核心用法。

---

## v0.1.0: init!

日期：2025-12-04  
状态：初始可用版本

**概述**

- 实现了 PubMed 检索 + BibTeX 导出基础功能。
- 添加可选的 Gemini 接口，用于为文献生成中文结构化总结并写入 `annote` 字段。
- 提供示例配置文件和依赖说明，方便在本地快速跑通。

**详细内容**

- 新增：`pubmed_bibtex.py`
  - 支持通过关键词检索 PubMed（使用 NCBI E-utilities：`esearch` + `efetch`）。
  - 按“Best Match”排序，支持限定最近 N 年、限制最大返回条数。
  - 解析 PubMed XML，生成包含以下字段的 BibTeX 条目：
    - `author`, `title`, `journal`, `year`, `volume`, `number`, `pages`, `doi`, `pmid`
    - `abstract`, `keywords`, `mesh_terms`, `language`, `article_type`
    - `affiliation`, `issn`, `eissn`, `url`, `pmcid`
    - 预留 `annote` 字段（用于后续 AI 总结或手工注释）。
  - 支持从命令行参数或 `.env` 读取检索配置（`PUBMED_QUERY`, `PUBMED_YEARS`, `PUBMED_MAX_RESULTS`, `PUBMED_OUTPUT` 等）。
  - 若配置了 `GEMINI_API_KEY` 和 `GEMINI_MODEL`，在生成 BibTeX 前会调用 Gemini：
    - 输入：文献的标题和摘要。
    - 要求输出固定结构的 JSON：
      - `summary_zh`: 中文 2–4 句总结文章内容。
      - `usage_zh`: 中文说明在论文/综述中如何引用这篇文章。
    - 将返回的 JSON 字符串原样写入 BibTeX 的 `annote` 字段。

- 新增：`gemini_summary.py`
  - 命令行工具，支持：
    - 通过 `--prompt` 传入文本，或从标准输入读取文本。
    - 使用 `GEMINI_API_KEY` 和 `GEMINI_MODEL` 调用 Gemini，将模型输出流式打印到终端。
  - 用于调试 prompt，或单独生成可手工填入 `annote` 的总结文本。

- 新增：`.env.example`
  - 提供 PubMed 与 Gemini 的示例配置键，包括：
    - `PUBMED_QUERY`, `PUBMED_YEARS`, `PUBMED_MAX_RESULTS`, `PUBMED_OUTPUT`
    - `PUBMED_EMAIL`, `PUBMED_API_KEY`
    - `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_TEMPERATURE`

- 新增：`README.md`
  - 面向终端用户的使用说明：环境准备、PubMed 检索示例、AI 接入示例、字段说明等。

- 新增：`docs/DEVELOPER.md`
  - 面向开发者的文档，介绍项目结构、配置优先级、设计思路及未来扩展规划。

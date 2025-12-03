# 版本更新记录（CHANGELOG）

本文件用于记录项目的版本更新历史，方便追踪功能演进和问题修复情况。约定如下：

- 按时间倒序记录版本（最新的在最上方）。
- 每个版本分为：日期、变更概述、详细内容。
- 版本号建议采用 `MAJOR.MINOR.PATCH` 格式，例如：`0.1.0`、`1.0.0` 等。

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


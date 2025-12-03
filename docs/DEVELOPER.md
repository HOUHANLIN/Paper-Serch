# PubMed + Gemini 项目开发者说明

本文件面向开发者，介绍项目结构、设计思路以及未来扩展计划，便于二次开发和维护。

---

## 1. 项目结构概览

当前仓库的核心文件结构如下：

- `pubmed_bibtex.py`  
  - 核心脚本：负责调用 NCBI PubMed E-utilities（`esearch` + `efetch`），解析 XML，生成 BibTeX 文件。  
  - 在检测到 Gemini 配置可用时，会对每篇文献调用 Gemini 生成中文总结，并写入 BibTeX 的 `annote` 字段。

- `gemini_summary.py`  
  - 命令行工具示例：对任意输入文本调用 Gemini 生成输出（流式打印）。  
  - 可用于调试提示词、生成手工填入 `annote` 的总结文本。

- `.env.example`  
  - 示例环境配置文件，展示所有可配置项：  
    - PubMed 相关：`PUBMED_QUERY`、`PUBMED_YEARS`、`PUBMED_MAX_RESULTS`、`PUBMED_OUTPUT`、`PUBMED_EMAIL`、`PUBMED_API_KEY`  
    - Gemini 相关：`GEMINI_API_KEY`、`GEMINI_MODEL`、`GEMINI_TEMPERATURE`

- `.env`  
  - 用户实际使用的本地配置文件（不会提交到 Git），由 `.env.example` 拷贝并修改而来。

- `requirements.txt`  
  - Python 依赖列表：当前主要包括 `requests`、`google-genai` 等。

- `README.md`  
  - 面向终端使用者的使用说明：环境准备、命令示例、输出说明等。

- `.gitignore`  
  - 忽略虚拟环境、缓存、临时文件以及生成的 `.bib` 和本地 `.env`。

---

## 2. 核心设计思路

### 2.1 配置来源与优先级

项目的设计目标之一是：**所有跟用户场景相关的配置都从环境/CLI 获取，脚本本身尽量不写死任何个人化参数**。

- PubMed 检索参数优先级（在 `pubmed_bibtex.py` 中）：  
  - `--query` 命令行参数  
  - `PUBMED_QUERY` 环境变量（通常来自 `.env`）  
  - 若两者都没有，脚本报错提示需要配置检索式。

- Gemini 模型参数优先级：  
  - 在 `gemini_summary.py` 中：`--model` > `GEMINI_MODEL`（否则报错要求配置）。  
  - 在 `pubmed_bibtex.py` 中：仅使用 `GEMINI_MODEL`，若未设置则自动跳过 AI 总结（仅生成常规 BibTeX）。

### 2.2 PubMed 检索与解析

`pubmed_bibtex.py` 的核心流程：

1. `_load_env()`  
   - 从 `.env` 中加载 `KEY=VALUE` 到 `os.environ`，只在当前脚本未定义该键时生效。

2. `search_pubmed()`  
   - 调用 `esearch.fcgi`：
     - `db=pubmed`  
     - `term=...`（检索式）  
     - `datetype=pdat`，`mindate` / `maxdate` 由 `years` 计算  
     - `sort=best match`  
   - 返回 PMID 列表。

3. `fetch_pubmed_details()`  
   - 调用 `efetch.fcgi`，通过 PMID 列表获取 XML。

4. `_extract_article_info()`  
   - 从 `MedlineCitation` / `Article` 等节点解析：
     - 基本字段：`pmid`、`title`、`journal`、`year`、`volume`、`issue`、`pages`  
     - 作者信息：`authors`（BibTeX 格式的 `Last, Initials and ...`）  
     - 摘要：合并多段 `AbstractText`，保留标签信息  
     - 关键词 / MeSH：`KeywordList`、`MeshHeadingList`  
     - 语言、文献类型、作者单位、ISSN / eISSN、URL、PMCID 等。
   - 构造内部用的 `dict`，供后续生成 BibTeX 使用。

5. `article_to_bibtex()`  
   - 将上述 `dict` 转为 `@article{...}` BibTeX 字符串：  
     - 对除 `annote` 外的字段做简单转义（`{`、`}`、`\`、`%`）及换行折行。  
     - `annote` 字段保留原始字符串（预期为 JSON），不做转义，方便下游解析。

6. `write_bibtex_file()`  
   - 遍历 `PubmedArticle` 列表，调用 `_extract_article_info()` 和 `article_to_bibtex()`，聚合写入目标 `.bib` 文件。
   - 若 Gemini 可用，会在生成 BibTeX 前先尝试为每篇文献填充 `annote`。

### 2.3 Gemini 调用与 annote 字段

在 `pubmed_bibtex.py` 中：

- `_init_gemini_client()`  
  - 从 `GEMINI_API_KEY`、`GEMINI_MODEL` 初始化 Gemini 客户端；失败时返回 `(None, None, None)` 并打印警告。  
  - 未设置 `GEMINI_MODEL` 时直接跳过 AI 总结。

- `_summarize_with_gemini()`  
  - 输入：单篇文献的 `info` 字典（包含 `title`、`journal`、`year`、`abstract` 等）。
  - 构造中文 prompt，要求模型输出一个固定结构的 JSON：
    - `summary_zh`：中文 2–4 句概括文章目的、方法、结论。  
    - `usage_zh`：中文说明如何在综述 / 论文中引用这篇文章。
  - 使用 `GEMINI_TEMPERATURE`（默认 0）创建 `GenerateContentConfig`，通过 `generate_content_stream` 流式获取文本。
  - 出错时打印警告并返回空字符串，避免阻塞主流程。

- `write_bibtex_file()` 中逻辑：
  - 如果 AI 调用返回非空字符串，就将其写入 `info["annote"]`。  
  - `article_to_bibtex()` 遇到 `annote` 时直接写入 `{...}`，不进行 BibTeX 转义，方便后续 JSON 解析。

在 `gemini_summary.py` 中：

- 提供独立的命令行接口（不依赖 PubMed）：  
  - 从 `--prompt` 或 stdin 读取输入。  
  - 使用 `GEMINI_MODEL`、`GEMINI_TEMPERATURE` 调用 Gemini，并把结果直接打印出来。  
  - 方便开发者单独调试 prompt 或生成自定义 `annote` 内容。

---

## 3. 项目未来发展方向

以下是一些可以逐步实现的扩展点，方便你或其他开发者继续演进本项目。

### 3.1 更完备的 BibTeX 生成与适配

- 支持更多 BibTeX 类型：`@article` 之外，引入 `@inproceedings`、`@book` 等。  
- 针对不同引用管理软件（Zotero、EndNote、Mendeley）微调字段映射与转义策略。  
- 增加对特殊字符（希腊字母、上标、下标）的更精细转义或 LaTeX 化处理。

### 3.2 AI 处理链自动化

- 实现从 `.bib` 反向解析 `annote` 为 JSON，对接前端或可视化界面。  
- 增加命令，例如：
  - `python pubmed_bibtex.py --update-annote-only input.bib output.bib`  
  - 只对已有 `.bib` 进行 AI 标注，不重复请求 PubMed。
- 针对长摘要或全文（将来接入全文 API）增加分段总结、主题提取、关键句抽取等能力。

### 3.3 高级检索与批量任务

- 在 `.env` 或命令行中支持多检索式批量任务：  
  - 例如读取一个包含多行检索式的文件，为每行生成独立 `.bib`。  
- 加入简单的检索式模板系统：  
  - 如：`TOPIC="dental implants"`, 自动扩展为包含相关 MeSH 词的复合检索式。

### 3.4 质量控制与测试

- 为核心函数（`search_pubmed`、`_extract_article_info`、`article_to_bibtex` 等）补充单元测试，使用本地小型 XML 片段作为样本。  
- 为 AI 总结部分设计“非在线”的快照测试（例如用固定的 mock 响应），保证 prompt 调整后输出结构不被破坏。

### 3.5 图形界面与集成

- 封装为简单的 GUI（如 PyQt / web 前端 + 后端 API），方便非程序用户操作：  
  - 输入关键词 → 选择年份/数量 → 一键生成 `.bib` + AI 总结。  
- 集成到现有科研工作流中，例如：  
  - 与 VSCode 插件或 Jupyter Notebook 联动，在写作时动态检索并插入引用。  

---

## 4. 贡献建议

- 保持配置无侵入：不要在脚本中写死个人场景（主题、模型名、TOKEN 数等），统一通过 `.env` 或命令行参数注入。  
- 遵循现有结构：  
  - PubMed 相关逻辑集中在 `pubmed_bibtex.py`，AI 相关逻辑通过清晰的 helper 函数（如 `_init_gemini_client`、`_summarize_with_gemini`）隔离。  
- 修改 prompt 或输出结构时：  
  - 同步更新 README 和本文件，说明输出 JSON 结构是否有变化。  

如果你计划进行较大改动（例如接入其他文献数据库、替换大模型提供方），建议在本文件中新增一个“小节”说明新的设计决策，方便后续维护者快速上手。  


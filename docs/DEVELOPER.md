# PubMed + Gemini 项目开发者说明

本文件面向开发者，介绍项目结构、设计思路以及未来扩展计划，便于二次开发和维护。

---

## 1. 项目结构概览

当前仓库的核心文件结构如下（v0.3.0 插件化架构）：

- `paper_sources/`
  - `base.py`：`ArticleInfo` 数据类与 `PaperSource` 协议，规范化文献元数据。
  - `pubmed.py`：默认的 PubMed 实现，负责检索与字段解析。
  - `registry.py`：数据源注册表，集中管理可用 `PaperSource` 实例。

- `ai_providers/`
  - `base.py`：`AiProvider` 协议与 `Noop`（不使用 AI）实现。
  - `gemini.py`：Gemini Provider，自动读取 `GEMINI_API_KEY` / `GEMINI_MODEL` 后启用。
  - `openai_provider.py`：OpenAI 占位 Provider，便于后续接入兼容 API。
  - `registry.py`：AI Provider 注册表，统一暴露 `list_providers()`、`get_provider()`。

- `services/`
  - `bibtex.py`：将 `ArticleInfo` 列表转换为 BibTeX 文本的通用函数。
  - `env_loader.py`、`keys.py`：环境变量、配置处理等通用工具。

- `pubmed_bibtex.py`
  - CLI 入口：
    - 读取 `.env`/参数，调用 `PubMedSource.search()`
    - 可通过 `--ai-provider` 指定 AI 总结（默认 `none`），复用 `ai_providers.registry`
    - 使用 `services/bibtex.build_bibtex_entries()` 输出 `.bib`

- `webapp.py` + `templates/index.html`
  - Flask Web 界面：表单可选择“文献数据源”“AI 模型”，统一走注册表。
  - 将检索结果与 AI 总结渲染为概要列表与 BibTeX 文本。

- 其他：
  - `gemini_summary.py`：独立的 Gemini 终端调用示例。
  - `.env.example` / `.env`：环境变量示例与实际配置。
  - `README.md`：用户说明；`docs/CHANGELOG.md` 与本文件用于记录版本与设计。

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

### 2.4 插件化数据源与 AI Provider（v0.3.0）

- 数据源：所有实现统一继承 `PaperSource` 协议，并在 `paper_sources/registry.py` 中注册。
  - Web/CLI 通过 `list_sources()` 获取展示名称，通过 `get_source(name)` 调用具体实现。
  - 默认内置 `PubMedSource`，其余站点可按需扩展并注册。
- AI Provider：实现 `AiProvider` 协议后在 `ai_providers/registry.py` 注册。
  - `Noop` 用于“无 AI”场景；`GeminiProvider` 根据环境变量动态启用；`OpenAIProvider` 作为占位示例。
  - `webapp.py` 及 `pubmed_bibtex.py` 统一调用 `get_provider()`，无需感知具体模型细节。

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
- 逐步演进为“AI 增强型”工作流：在同一套接口下支持多个大模型（如 Gemini、DeepSeek、Qwen、ChatGPT 等），通过配置自由切换，同时保持输出结构一致，方便下游工具和界面消费。  

### 3.3 高级检索与批量任务

- 在 `.env` 或命令行中支持多检索式批量任务：  
  - 例如读取一个包含多行检索式的文件，为每行生成独立 `.bib`。  
- 加入简单的检索式模板系统：  
  - 如：`TOPIC="dental implants"`, 自动扩展为包含相关 MeSH 词的复合检索式。
 - 在此基础上，引入“AI 检索助手/Agent”：根据用户用自然语言描述的研究问题，自动生成和优化 PubMed 等站点的检索式，并能根据返回结果数量与相关性自动放宽或收紧范围。  

### 3.4 多文献源与数据融合

- 在 PubMed 之外，逐步接入更多文献站点和元数据服务（如 arXiv、CrossRef、Semantic Scholar、开放获取期刊平台等），形成统一的“多源检索”能力。  
- 对不同来源的文献信息做规范化处理，内部采用统一字段集合，便于 BibTeX 导出和后续分析。  
- 支持跨来源的去重、合并和简单质量评估，帮助用户快速获得相对完整且重复率较低的文献集合。  

### 3.5 质量控制与测试

- 为核心函数（`search_pubmed`、`_extract_article_info`、`article_to_bibtex` 等）补充单元测试，使用本地小型 XML 片段作为样本。  
- 为 AI 总结部分设计“非在线”的快照测试（例如用固定的 mock 响应），保证 prompt 调整后输出结构不被破坏。

### 3.6 图形界面与集成

- 封装为简单的 GUI（如 PyQt / web 前端 + 后端 API），方便非程序用户操作：  
  - 输入关键词 → 选择年份/数量 → 一键生成 `.bib` + AI 总结。  
- 集成到现有科研工作流中，例如：  
  - 与 VSCode 插件或 Jupyter Notebook 联动，在写作时动态检索并插入引用。  

### 3.7 可扩展架构与插件化生态

- 将“文献来源”和“AI 能力”设计为可插拔组件：通过清晰的扩展点（配置项、接口约定）接入新的文献站点和新的大模型，而不需要大规模改动现有代码。  
- 始终保留“无 AI 模式”：即便关闭所有模型调用，本项目仍然可以完成基础检索与 BibTeX 导出，便于在受限环境或教学场景中使用。  
- 随着用户需求增多，可以探索开放“插件生态”的可能：允许他人为本项目编写自定义的检索模块、AI 模块或可视化模块，在保持核心简洁的前提下，让项目自然成长为一个轻量的 AI 文献工作流平台。  

---

## 4. 贡献建议

- 保持配置无侵入：不要在脚本中写死个人场景（主题、模型名、TOKEN 数等），统一通过 `.env` 或命令行参数注入。  
- 遵循现有结构：  
  - PubMed 相关逻辑集中在 `pubmed_bibtex.py`，AI 相关逻辑通过清晰的 helper 函数（如 `_init_gemini_client`、`_summarize_with_gemini`）隔离。  
- 修改 prompt 或输出结构时：  
  - 同步更新 README 和本文件，说明输出 JSON 结构是否有变化。  

如果你计划进行较大改动（例如接入其他文献数据库、替换大模型提供方），建议在本文件中新增一个“小节”说明新的设计决策，方便后续维护者快速上手。  

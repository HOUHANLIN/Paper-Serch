# PubMed 文献检索与 BibTeX 导出脚本使用说明（v0.3.0）

本脚本 `pubmed_bibtex.py`（当前版本：**v0.3.0**）用于：

- 使用关键词在 PubMed / Embase 等数据源上检索文献
- 限制时间范围（例如最近 5 年）  
- 按 PubMed 的 “Best Match（最佳匹配）” 排序  
- 选取前 N 篇文献并导出为 `.bib` 格式的 BibTeX 文件  
- （可选）调用 Gemini 自动生成中文总结，写入 `annote` 字段
- 预留多数据源与多 AI 模型接口，可在 Web 界面下拉选择
- 通过一个简单的 Web 前端在浏览器里完成检索与导出

### v0.3.0 更新速览

- **插件化架构**：新增 `paper_sources/` 与 `ai_providers/` 模块，文献来源与 AI 提供方均通过注册表管理，后续接入新站点/模型无需重写主流程。
- **统一选择**：Web 表单支持选择“文献数据源”和“AI 模型”，默认可选“仅检索”“Gemini（自动检测配置）”“OpenAI 占位”。
- **BibTeX 服务化**：`services/bibtex.py` 抽取了 BibTeX 生成逻辑，便于其他数据源或未来 API 复用。

非常适合用于：快速收集某一主题近几年代表性文献，然后导入到 EndNote、Zotero、NoteExpress 等文献管理工具中。

---

## 1. 环境准备

假设你已经在当前目录下创建了虚拟环境 `venv`，并已安装必要依赖。

在终端进入脚本所在目录后，先激活虚拟环境：

```bash
source venv/bin/activate
```

若未安装依赖，可以在虚拟环境中运行：

```bash
pip install -r requirements.txt
```

> 其中 `flask` 用于本地 Web 前端界面；`requests` 和 `google-genai` 分别用于访问 PubMed API 与 Gemini。

---

## 2. 基本用法

脚本仅支持通过 `.env` 读取配置：复制 `.env.example` 为 `.env`，填写好 `PUBMED_QUERY`、`PUBMED_YEARS`（或 Embase 对应的 `EMBASE_*`、`EMBASE_API_KEY`）等后，直接运行：

```bash
python pubmed_bibtex.py
```

脚本会自动从 `.env` 中读取：

- `PAPER_SOURCE`：数据源，默认 `pubmed`，可改为 `embase`
- `PUBMED_QUERY` / `EMBASE_QUERY`：默认检索式
- `PUBMED_YEARS` / `EMBASE_YEARS`：默认时间范围
- `PUBMED_MAX_RESULTS` / `EMBASE_MAX_RESULTS`：默认最大条数
- `PUBMED_OUTPUT` / `EMBASE_OUTPUT`：默认输出 `.bib` 文件名

---

## 2.3 使用 Web 前端（可视化界面）

安装依赖并激活虚拟环境后，启动 Web 前端：

```bash
source venv/bin/activate
python webapp.py
```

浏览器访问 `http://127.0.0.1:5000`，在页面中输入检索式、年份和数量，点击“生成 BibTeX” 即可；Email 和 NCBI API Key 可选（不填则使用 `.env` / 环境变量）。若已配置 `GEMINI_API_KEY` 和 `GEMINI_MODEL`，页面会提示“已启用 Gemini AI 总结”，并将总结写入 `annote` 字段。

界面顶部可以选择文献数据源（当前内置 PubMed，后续可扩展其他站点）以及 AI 模型（内置占位的 OpenAI 选项和自动检测的 Gemini 配置），便于未来接入新的 API 而无需改动前端。

> 提示：前端表单初始值默认全部留空，若未填写则后端会使用 `.env` 中的配置作为回退值。

---

## 2.4 使用 Docker / docker-compose 运行

可以用 Docker 直接运行 Web 前端。

### 2.4.1 准备环境变量

确保当前目录下存在 `.env` 文件（可从 `.env.example` 拷贝修改），包括：

- PubMed 相关配置：`PUBMED_QUERY`、`PUBMED_YEARS`、`PUBMED_MAX_RESULTS`、`PUBMED_OUTPUT`、`PUBMED_EMAIL`、`PUBMED_API_KEY` 等；  
- Gemini 相关配置（可选）：`GEMINI_API_KEY`、`GEMINI_MODEL` 等。  

该 `.env` 不会打包进镜像（已在 `.dockerignore` 中忽略），但会在启动容器时作为环境变量加载。

### 2.4.2 通过 Docker 直接运行 Web 前端

在项目根目录执行：

```bash
docker build -t pubmed-bibtex .
docker run --rm -p 5000:5000 --env-file .env pubmed-bibtex
```

然后访问 `http://127.0.0.1:5000`。

### 2.4.3 使用 docker-compose 运行

项目根目录已提供 `docker-compose.yml`：

```bash
docker-compose up --build
```

停止服务：

```bash
docker-compose down
```

---

## 2.5 切换文献数据源与 AI 模型

当前版本默认内置：

- 文献数据源：
  - `pubmed`（`paper_sources/pubmed.py`）
  - `embase`（`paper_sources/embase.py`，需 `EMBASE_API_KEY`）
- AI 总结：
  - `none`：不调用模型，仅返回检索结果
  - `gemini`：自动检测 `GEMINI_API_KEY`/`GEMINI_MODEL` 后启用
  - `openai`：占位符，便于后续接入 OpenAI 或兼容 API

使用方式：

- **Web 前端**：首页下拉框可选择“文献数据源”“AI 模型”，提交后会按所选组合检索并生成 BibTeX。

开发者可在注册表中添加新的数据源/模型（见下文扩展指南），无需修改现有 Web 业务流程。

---

## 3. 配置项说明（通过 `.env` 设置）

将下列环境变量写入 `.env`（或在运行前导出），脚本会自动读取：

- `PUBMED_QUERY`（必填）
  - PubMed 检索关键词或检索式（支持 AND、OR、括号等 PubMed 常用语法）。

- `PUBMED_YEARS`（可选，默认：`5`）
  - 限制检索的“发表时间”范围为最近多少年。
  - 例如：设置为 `5` 表示从今天往前推 5 年内发表的文献。

- `PUBMED_MAX_RESULTS`（可选，默认：`10`）
  - 最多返回多少篇文献。
  - 例如：设置为 `20` 表示按 Best Match 排序后取前 20 篇。

- `PUBMED_OUTPUT`（可选，默认：`pubmed_results.bib`）
  - 指定导出的 BibTeX 文件名。

- `PUBMED_EMAIL`（推荐）
  - 提供给 NCBI 的联系邮箱，有利于合规使用 API。

- `PUBMED_API_KEY`（可选）
  - 若你在 NCBI 申请了 API Key，可以在这里填写，以获得更高的访问限额和更稳定的服务。

### Embase（Elsevier API）配置

Embase 通过 Elsevier API 检索，需要在 `.env` 中补充：

- `EMBASE_API_KEY`（必填）
  - Elsevier 提供的 Embase API Key。
- `EMBASE_INSTTOKEN`（可选）
  - 若机构订阅要求，填入机构 token；否则可留空。
- `EMBASE_QUERY`（可选）
  - 若未填写则复用通用的 `QUERY`/`PUBMED_QUERY`。可按需要单独设置 Embase 检索式。
- `EMBASE_YEARS`、`EMBASE_MAX_RESULTS`、`EMBASE_OUTPUT`
  - 若留空则退回到 PubMed 的默认值（5 年、10 条、`pubmed_results.bib`）。

---

## 4. 典型示例

### 4.1 一般主题检索示例

1. 编辑 `.env`，填入：
   - `PUBMED_QUERY="cancer"`
   - `PUBMED_YEARS=5`
   - `PUBMED_MAX_RESULTS=10`
   - `PUBMED_OUTPUT="cancer_top10.bib"`
2. 运行脚本：

```bash
source venv/bin/activate && \
python pubmed_bibtex.py
```

生成的 BibTeX 将保存到 `cancer_top10.bib`。

---

### 4.2 AI 在口腔种植学中的应用（你当前的主题）

如果你想检索 “人工智能（AI）在口腔种植学中的应用”，可以在 `.env` 中设置：

```env
PUBMED_QUERY="artificial intelligence" AND ("dental implants" OR "implant dentistry" OR "oral implantology")
PUBMED_YEARS=5
PUBMED_MAX_RESULTS=10
PUBMED_OUTPUT="ai_implant_dentistry.bib"
```

保存后执行：

```bash
source venv/bin/activate && \
python pubmed_bibtex.py
```

执行完成后，当前目录将生成 `ai_implant_dentistry.bib` 文件，你可以将其导入到文献管理工具中，用于写作综述或毕业论文。

---

## 5. 输出说明（BibTeX 格式）

生成的 BibTeX 条目大致类似：

```bibtex
@article{FirstAuthor_2023_12345678,
  author = {FirstAuthor, A and SecondAuthor, B},
  title = {Article Title ...},
  journal = {J Dent Res},
  year = {2023},
  volume = {102},
  number = {4},
  pages = {123-130},
  doi = {10.xxxx/xxxxxxx},
  pmid = {12345678},
  abstract = {This study aimed to ...},
  keywords = {dental implants; artificial intelligence; ...},
  mesh_terms = {Dental Implants; Algorithms; ...},
  language = {English},
  article_type = {Journal Article; Review},
  affiliation = {Department of ... | School of ...},
  issn = {0022-0345},
  eissn = {1544-0591},
  url = {https://pubmed.ncbi.nlm.nih.gov/12345678/},
  pmcid = {PMC1234567},
  annote = {AI summary will be inserted here ...}
}
```

脚本会自动：

- 从 PubMed XML 中解析作者、题目、期刊、年份、卷期、页码、DOI、PMID、摘要（abstract）、关键词（keywords）、MeSH 词（mesh_terms）、语言（language）、文献类型（article_type）、作者单位（affiliation）、ISSN/eISSN、PubMed 链接（url）、PMCID 等信息  
- 生成适用于大多数文献管理工具的标准 `@article{}` 条目，其中 `abstract` 字段可直接用于预览摘要；`annote` 字段默认留空，你可以手动使用 AI 工具生成总结后填入，也可以结合本项目的 Gemini 接口实现自动填充  

---

## 6. AI 接入示例（Gemini，预留给 annote 字段）

本项目中额外提供了一个脚本 `gemini_summary.py`，展示如何使用 `google-genai` 调用 Gemini 模型生成文本（例如对摘要/全文进行自动总结），后续你可以把生成的总结结果写入 BibTeX 的 `annote` 字段中，或结合 `pubmed_bibtex.py` 做自动 AI 标注（当前版本中，`pubmed_bibtex.py` 已具备调用 Gemini 并写入 `annote` 的能力）。 

### 6.1 安装与环境变量

在虚拟环境中安装依赖：

```bash
source venv/bin/activate
pip install -r requirements.txt
```

在终端或 `.env` 中配置 Gemini 的相关环境变量：

```bash
export GEMINI_API_KEY="你的_gemini_api_key"
export GEMINI_MODEL="gemini-2.5-flash"
export GEMINI_TEMPERATURE=0
```

### 6.2 使用示例

直接用命令行传入一个提示词：

```bash
python gemini_summary.py \
  --prompt "请用中文总结下面这段 PubMed 摘要，并给出口腔种植学应用启示：......"
```

或从管道/文件读取内容，例如将某条文献的摘要作为输入：

```bash
cat some_abstract.txt | python gemini_summary.py
```

脚本会把 Gemini 的输出直接打印到终端，你可以手动复制到相应 BibTeX 条目的 `annote` 字段中。  
当前版本中，`pubmed_bibtex.py` 也会在有可用 Gemini 配置时自动读取标题和摘要，向 Gemini 发送结构化指令，请模型返回如下 JSON 结构，并将完整 JSON 字符串写入每条文献的 `annote` 字段：

```json
{
  "summary_zh": "用中文 2-4 句话概括文章的研究目的、方法和主要结论",
  "usage_zh": "用中文说明在撰写综述或论文时，这篇文章可以如何被引用或使用"
}
```

---

## 7. 常见问题

- **Q：运行时报网络错误（如无法解析域名或连接失败）怎么办？**  
  A：请确认当前机器可以访问外网，并且网络环境允许访问 `https://eutils.ncbi.nlm.nih.gov`。若在受限网络环境下（如医院/学校内网），可能需要代理或更换网络。  

- **Q：能否调整检索主题或时间范围？**  
  A：可以，通过修改 `--query`、`--years` 和 `--max-results` 等参数即可灵活调整。  

- **Q：导出的 BibTeX 能直接用于 LaTeX 吗？**  
  A：脚本会对部分特殊字符（如 `{`、`}`、`%` 等）做转义处理，一般可直接用于 LaTeX 与主流参考文献样式。若某些条目有特殊字符显示问题，可手动微调对应条目。  


如需根据你的具体课题（例如某一 AI 算法、某一系统综述等）定制更精准的检索式，或自动化 “abstract → AI 总结 → annote” 的全流程，我也可以帮你一起优化和实现。  


---

## 8. 扩展指南：接入新的数据源或 AI 模型

### 8.1 新增文献数据源（例如 arXiv/CrossRef）

1. 创建文件 `paper_sources/<your_source>.py`，实现 `PaperSource` 协议：
   - 必需属性：`name`、`display_name`
   - 必需方法：`search(query, years, max_results, **kwargs) -> List[ArticleInfo]`
   - 复用 `ArticleInfo` 数据类字段，按需填充 `pmid`、`doi`、`url` 等。
2. 在 `paper_sources/registry.py` 中将实例加入 `_SOURCES` 注册表。
3. Web 会自动出现新的数据源选项，无需改动 `webapp.py`。

### 8.2 新增 AI 提供方（例如 OpenAI 兼容接口）

1. 创建文件 `ai_providers/<provider>.py`，实现 `AiProvider` 协议：
   - 必需属性：`name`、`display_name`
   - 必需方法：`summarize(info: ArticleInfo) -> str`，返回写入 `annote` 的字符串（可为 JSON）。
2. 在 `ai_providers/registry.py` 中注册实例；如需按环境变量动态启用，可参考 `GeminiProvider` 的 `get_default_gemini_provider()` 实现。
3. 前端下拉会自动出现新的模型名称，选择后即可调用。

### 8.3 BibTeX 生成复用

- 通过 `services/bibtex.build_bibtex_entries(articles)` 将任意 `ArticleInfo` 列表生成 BibTeX 字符串和计数，便于不同来源复用同一导出逻辑。
- 如需调整字段映射或转义策略，可在该模块集中修改，无需遍历各个数据源实现。

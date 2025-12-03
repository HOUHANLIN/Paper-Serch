# PubMed 文献检索与 BibTeX 导出脚本使用说明

本脚本 `pubmed_bibtex.py` 用于：

- 使用关键词在 PubMed 上检索文献  
- 限制时间范围（例如最近 5 年）  
- 按 PubMed 的 “Best Match（最佳匹配）” 排序  
- 选取前 N 篇文献并导出为 `.bib` 格式的 BibTeX 文件

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

---

## 2. 基本用法

脚本支持两种配置方式：

- 完全使用命令行参数；
- 在 `.env` 中写好默认配置（推荐），然后直接运行 `python pubmed_bibtex.py`。

### 2.1 使用命令行参数

脚本基本调用形式如下：

```bash
python pubmed_bibtex.py \
  --query "你的检索式" \
  --years 5 \
  --max-results 10 \
  --output result.bib
```

运行后，当前目录会生成一个 `result.bib` 文件，其中包含从 PubMed 获取的文献信息（BibTeX 格式）。

你也可以先查看帮助信息：

```bash
python pubmed_bibtex.py --help

### 2.2 使用 `.env` 默认配置（推荐）

你可以复制 `.env.example` 为 `.env`，填写好 `PUBMED_QUERY`、`PUBMED_YEARS` 等后，直接运行：

```bash
python pubmed_bibtex.py
```

此时脚本会自动从 `.env` 中读取：

- `PUBMED_QUERY`：默认检索式  
- `PUBMED_YEARS`：默认时间范围  
- `PUBMED_MAX_RESULTS`：默认最大条数  
- `PUBMED_OUTPUT`：默认输出 `.bib` 文件名  
```

---

## 3. 参数说明

脚本支持的主要参数如下：

- `--query` / `-q`（必填）  
  - PubMed 检索关键词或检索式（支持 AND、OR、括号等 PubMed 常用语法）。  

- `--years` / `-y`（可选，默认：`5`）  
  - 限制检索的“发表时间”范围为最近多少年。  
  - 例如：`--years 5` 表示从今天往前推 5 年内发表的文献。  

- `--max-results` / `-n`（可选，默认：`10`）  
  - 最多返回多少篇文献。  
  - 例如：`--max-results 20` 表示按 Best Match 排序后取前 20 篇。  

- `--output` / `-o`（可选，默认：`pubmed_results.bib`）  
  - 指定导出的 BibTeX 文件名。  
  - 例如：`--output ai_implant_dentistry.bib`。  

- `--email`（推荐）  
  - 提供给 NCBI 的联系邮箱，有利于合规使用 API。  

- `--api-key`（可选）  
  - 若你在 NCBI 申请了 API Key，可以在这里填写，以获得更高的访问限额和更稳定的服务。  

---

## 4. 典型示例

### 4.1 一般主题检索示例

例如，检索最近 5 年关于 “癌症（cancer）” 的前 10 篇代表性文献，并导出为 `cancer_top10.bib`：

```bash
source venv/bin/activate && \
python pubmed_bibtex.py \
  -q "cancer" \
  -y 5 \
  -n 10 \
  -o cancer_top10.bib
```

---

### 4.2 AI 在口腔种植学中的应用（你当前的主题）

如果你想检索 “人工智能（AI）在口腔种植学中的应用”，可以使用下面这个英文检索式：

```text
"artificial intelligence" AND ("dental implants" OR "implant dentistry" OR "oral implantology")
```

搭配脚本的完整命令示例如下（检索最近 5 年，取前 10 篇文献，导出为 `ai_implant_dentistry.bib`）：

```bash
source venv/bin/activate && \
python pubmed_bibtex.py \
  -q '"artificial intelligence" AND ("dental implants" OR "implant dentistry" OR "oral implantology")' \
  -y 5 \
  -n 10 \
  -o ai_implant_dentistry.bib
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

---

如需根据你的具体课题（例如某一 AI 算法、某一系统综述等）定制更精准的检索式，或自动化 “abstract → AI 总结 → annote” 的全流程，我也可以帮你一起优化和实现。  

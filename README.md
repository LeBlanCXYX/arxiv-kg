# OpenKG：论文知识图谱与问答

基于 ArXiv + Semantic Scholar + 大模型的论文知识图谱构建与可视化、图谱问答（Graph RAG）。

**推荐 Python 版本：3.10**

---

## 1. 环境准备

### 1.1 创建虚拟环境（推荐）

```bash
# 使用 Python 3.10 创建虚拟环境
python3.10 -m venv .venv

# 激活（Windows）
.venv\Scripts\activate

# 激活（Linux / macOS）
source .venv/bin/activate
```

### 1.2 安装依赖

```bash
pip install -r requirements.txt
```

---

## 2. API Key 配置（必做一步）

所有需要调用大模型的脚本（`main.py`、`top_citations_kg.py --llm`、`app_qa.py`）都从**统一配置**读取 API Key。

### 方式一：本地配置文件（推荐）

1. 复制示例配置并改名：
   ```bash
   cp config_local.py.example config_local.py
   ```
   Windows 下：
   ```cmd
   copy config_local.py.example config_local.py
   ```

2. 编辑 `config_local.py`，填入你的 Key：
   - **DeepSeek**：`API_KEY`、`BASE_URL = "https://api.deepseek.com"`、`MODEL_NAME = "deepseek-chat"`
   - **OpenAI**：`API_KEY`、`BASE_URL = "https://api.openai.com/v1"`、`MODEL_NAME = "gpt-4-turbo"` 等

**注意**：不要提交 `config_local.py` 到版本库（已通过 `.gitignore` 忽略）。

### 方式二：环境变量

不创建 `config_local.py` 时，可从环境变量读取：

- `OPENAI_API_KEY`：API Key
- `OPENAI_BASE_URL`（可选）：如 `https://api.deepseek.com`
- `OPENAI_MODEL_NAME`（可选）：如 `deepseek-chat`

---

## 3. 项目脚本说明

| 脚本 | 作用 | 是否需要 API Key |
|------|------|------------------|
| `main.py` | 单篇论文：ArXiv 元数据 + LLM 抽取 + Semantic Scholar 引用 → `result.json` | 是 |
| `top_citations_kg.py` | 指定论文 + Top N：该论文引用/被引中引用量前 N 篇（不递归）→ JSON + HTML | 仅 `--llm` 时需要 |
| `recursive_citations_kg.py` | 递归展开：按深度 d 与每层 top-k 引用/被引，逐层展开 → JSON + HTML | 仅 `--llm` 时需要 |
| `visualize.py` | 将任意知识图谱 JSON 转为 ECharts 力导向图 HTML | 否 |
| `app_qa.py` | 基于知识图谱的问答（Graph RAG） | 是 |

---

## 4. 使用方式

### 4.1 单篇论文知识图谱（main.py）

从一篇论文的 ArXiv ID 生成 `result.json`（含元数据、LLM 抽取、引用关系）：

```bash
python main.py
```

默认使用 ArXiv ID `1706.03762`（Transformer）。如需改 ID，可编辑 `main.py` 末尾的 `target_id`。

### 4.2 Top 引用知识图谱（top_citations_kg.py）

根据一篇论文的 ArXiv ID 和数字 N，生成「该论文引用的论文」与「引用该论文的论文」中**引用量各前 N 篇**的图谱（不递归展开），并输出 JSON 与 HTML：

```bash
# 不调用 LLM，只做引用网络 + 元数据
python top_citations_kg.py 1706.03762 -n 5

# 调用 LLM 做深度抽取（需已配置 API Key）
python top_citations_kg.py 1706.03762 -n 5 --llm
```

- 输出：`top_citations_kg_<arxiv_id>.json`、`top_citations_kg_<arxiv_id>.html`
- 使用 conda 时：`conda activate kg` 后再运行上述命令

### 4.3 递归引用知识图谱（recursive_citations_kg.py）

在 top 引用的基础上按**深度**递归：每层对当前论文取 top-k 引用与被引，直到达到深度 d（复用 `top_citations_kg` 的拉取与可视化）。

```bash
# 每层 top 5，深度 2（本论文 + 一层邻接 + 二层邻接）
python recursive_citations_kg.py 1706.03762 -k 5 -d 2

# 每层 top 10，深度 3，并做 LLM 深度抽取
python recursive_citations_kg.py 1706.03762 -k 10 -d 3 --llm
```

- 输出：`recursive_kg_<arxiv_id>_k<k>_d<d>.json`、`recursive_kg_<arxiv_id>_k<k>_d<d>.html`
- `-k` 越大、`-d` 越大，请求量越多，耗时长且更容易触发 ArXiv/S2 限流，建议先用小参数试跑。

### 4.4 可视化（visualize.py）

将任意符合项目格式的知识图谱 JSON 转成可拖拽的 ECharts 力导向图 HTML：

```bash
# 默认：final_kg_5_papers.json → knowledge_graph.html
python visualize.py

# 指定输入与输出
python visualize.py result.json -o result.html
python visualize.py top_citations_kg_1706.03762.json -o kg.html
python visualize.py recursive_kg_1706.03762_k5_d2.json -o recursive_kg.html
```

### 4.5 图谱问答（app_qa.py）

基于已有知识图谱 JSON 做问答（仅根据图谱事实回答，不编造）：

```bash
# 默认使用 result.json
python app_qa.py

# 指定图谱文件（如 top_citations 生成的 JSON）
python app_qa.py top_citations_kg_1706.03762.json
```

在提示符下输入问题，输入 `exit` 退出。

---

## 5. 输出文件结构

- `result.json`：main.py 生成，单篇论文图谱
- `top_citations_kg_<arxiv_id>.json` / `.html`：top_citations_kg.py 生成（不递归）
- `recursive_kg_<arxiv_id>_k<k>_d<d>.json` / `.html`：recursive_citations_kg.py 生成（按深度递归）
- `knowledge_graph.html`：visualize.py 默认输出
- 图谱 JSON 统一包含：`paper_metadata`、`knowledge_graph.entities`、`knowledge_graph.triples`（递归输出还含 `top_k`、`depth`）

---

## 6. 依赖说明

- **arxiv**：拉取 ArXiv 论文元数据
- **requests**：调用 Semantic Scholar API
- **openai**：调用兼容 OpenAI 接口的大模型（DeepSeek / OpenAI 等）

配置均通过 `config.py` 读取，Key 来自 `config_local.py` 或环境变量。

---

## 7. 常见问题

- **未配置 API Key 就运行 main.py / app_qa.py / top_citations_kg.py --llm**  
  会提示先配置：复制 `config_local.py.example` 为 `config_local.py` 并填入 Key，或设置 `OPENAI_API_KEY`。

- **visualize 打开的 HTML 里部分节点没有边**  
  多为 LLM 返回了 subject/object 或 E1/E2 等 ID；当前脚本已做兼容与解析，若仍异常可重新生成 JSON（如对 top_citations_kg 使用 `--llm` 再跑一次）。

- **推荐 Python 版本**  
  建议使用 **Python 3.10** 创建虚拟环境并安装 `requirements.txt`，以减少兼容性问题。

- **打开 HTML 后图表不显示（CDN 超时 / Tracking Prevention）**  
  生成器会优先使用与 HTML **同目录**下的 `echarts.min.js`；若不存在则使用 unpkg CDN。若网络无法访问 CDN，请将 [echarts.min.js](https://unpkg.com/echarts@5.4.3/dist/echarts.min.js) 下载到与 `.html` 同一目录，刷新页面即可。项目根目录已附带一份 `echarts.min.js` 时，新生成的 HTML 会自动使用本地文件。

- **递归/大量爬取时 S2 速率限制或未按 k/d 爬完**  
  Semantic Scholar 无 Key 时约 100 次/5 分钟。脚本已做：每次 S2 请求前固定间隔 3 秒、遇 429/502/503 时自动指数退避重试（5s→10s→20s→40s），直到成功或重试用尽。若仍经常中断，可适当减小 `-k` 或 `-d`；或到 [Semantic Scholar](https://www.semanticscholar.org/product/api) 申请免费 API Key，待项目支持 `S2_API_KEY` 后可提高 S2 限额、减少 429。

- **大量 ArXiv 拉取失败（503 / 429）**  
  ArXiv 与 Semantic Scholar 是两套服务，ArXiv 建议约 3 秒/次请求；补全元数据时会对多篇连续请求，若请求过频或 ArXiv 暂时过载会返回 503/429，单次失败不会重试。可稍后重跑、或减小 `-k`/`-d` 以降低请求量。Semantic Scholar 的 API Key **不能**提高 ArXiv 限额。

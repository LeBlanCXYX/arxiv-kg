"""
基于 Top 引用的知识图谱生成器 (Top Citations KG)
功能：输入一篇论文的 arxiv id 和数字 N，自动查找：
  - 该论文引用的论文中引用量最靠前的 N 篇（references）
  - 引用该论文的论文中引用量最靠前的 N 篇（citations）
不递归查找这些相关论文的引用/被引用。相关论文必须有摘要、作者等元数据。
输出：JSON 知识图谱 + 可视化 HTML（类似 visualize）

运行环境：需先 conda 激活名为 kg 的环境
  conda activate kg
  python top_citations_kg.py <arxiv_id> -n <N>
示例：
  python top_citations_kg.py 1706.03762 -n 5
  python top_citations_kg.py 1706.03762 -n 3 --llm
若在 Windows 下用 conda run 出现编码错误，请直接在已激活 kg 的终端中运行上述命令。
"""

import arxiv
import json
import os
import requests
import time
import sys
import argparse
from openai import OpenAI

from config import API_KEY, BASE_URL, MODEL_NAME, is_api_configured
from class_schema import (
    get_all_type_names,
    normalize_entity_type,
    get_types_for_llm_prompt,
    get_categories_for_entities,
)
ALLOWED_TYPES = get_all_type_names()


def fetch_arxiv_paper(paper_id):
    """
    获取 ArXiv 论文的元数据（摘要、作者、日期等）
    """
    print(f"[*] [ArXiv] 获取论文元数据: {paper_id} ...")
    client = arxiv.Client()
    search = arxiv.Search(id_list=[paper_id])
    try:
        paper = next(client.results(search))
        return {
            "id": paper_id,
            "title": paper.title,
            "abstract": paper.summary,
            "published_date": paper.published.strftime("%Y-%m-%d"),
            "pdf_url": paper.pdf_url,
            "authors": [a.name for a in paper.authors],
        }
    except (StopIteration, Exception) as e:
        print(f"❌ ArXiv 获取失败 {paper_id}: {e}")
        return None


def _request_s2_with_retry(url, max_retries=4, base_delay=5):
    """请求 S2 API，遇 429 时指数退避重试。无 Key 时 S2 约 100 次/5 分钟，故请求前留间隔。"""
    for attempt in range(max_retries + 1):
        time.sleep(3 if attempt == 0 else 0)  # 每次调用前间隔，降低触发 429 概率
        try:
            r = requests.get(url, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                delay = base_delay * (2 ** attempt)
                print(f"   ⚠️ 速率限制 (429)，{delay} 秒后重试 ({attempt + 1}/{max_retries + 1})...")
                time.sleep(delay)
                continue
            if r.status_code == 404:
                return None
            if attempt < max_retries and r.status_code in (503, 502):
                delay = base_delay * (2 ** attempt)
                print(f"   ⚠️ 服务暂时不可用 ({r.status_code})，{delay} 秒后重试...")
                time.sleep(delay)
                continue
            return None
        except Exception as e:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                print(f"   ⚠️ 请求异常: {e}，{delay} 秒后重试...")
                time.sleep(delay)
            else:
                raise
    return None


def fetch_paper_from_semantic_scholar(paper_id_s2):
    """
    通过 Semantic Scholar paperId 获取论文的 title, abstract, authors（用于无 ArXiv ID 的论文）
    """
    url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id_s2}?fields=title,abstract,authors,year"
    try:
        data = _request_s2_with_retry(url)
        if not data:
            return None
        authors = [a.get("name") or "" for a in data.get("authors", [])]
        return {
            "title": data.get("title") or "",
            "abstract": data.get("abstract") or "",
            "authors": authors,
            "published_date": str(data.get("year") or ""),
            "pdf_url": "",
        }
    except Exception as e:
        print(f"   ⚠️ S2 获取失败 {paper_id_s2}: {e}")
        return None


def fetch_related_papers_via_semantic_scholar(arxiv_id, top_n=5):
    """
    获取该论文的 references 和 citations，并按引用量排序各取前 top_n 篇。
    遇 429 时指数退避重试，避免因速率限制导致漏爬。
    """
    print(f"[*] [S2] 获取引用关系 (top {top_n}): {arxiv_id} ...")
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/ARXIV:"
        + arxiv_id
        + "?fields=title,year,citationCount,"
        "references.title,references.externalIds,references.citationCount,references.year,references.paperId,"
        "citations.title,citations.externalIds,citations.citationCount,citations.year,citations.paperId"
    )
    try:
        data = _request_s2_with_retry(url, max_retries=4, base_delay=5)
        if not data:
            print("   ⚠️ 未获取到数据（未收录或已达重试上限）")
            return {"references": [], "citations": []}
        references = []
        if data.get("references"):
            for item in data["references"]:
                if not item.get("title"):
                    continue
                arxiv_id_ref = None
                if item.get("externalIds") and item["externalIds"].get("ArXiv"):
                    arxiv_id_ref = item["externalIds"]["ArXiv"]
                references.append({
                    "title": item["title"],
                    "arxiv_id": arxiv_id_ref,
                    "citation_count": item.get("citationCount") or 0,
                    "year": item.get("year") or 0,
                    "paper_id_s2": item.get("paperId"),
                })
        references = sorted(
            references, key=lambda x: (x["citation_count"] or 0), reverse=True
        )[:top_n]

        citations = []
        if data.get("citations"):
            for item in data["citations"]:
                if not item.get("title"):
                    continue
                arxiv_id_cite = None
                if item.get("externalIds") and item["externalIds"].get("ArXiv"):
                    arxiv_id_cite = item["externalIds"]["ArXiv"]
                citations.append({
                    "title": item["title"],
                    "arxiv_id": arxiv_id_cite,
                    "citation_count": item.get("citationCount") or 0,
                    "year": item.get("year") or 0,
                    "paper_id_s2": item.get("paperId"),
                })
        citations = sorted(
            citations, key=lambda x: (x["citation_count"] or 0), reverse=True
        )[:top_n]

        print(f"   --> 参考文献 top{top_n}: {len(references)} 篇, 被引文献 top{top_n}: {len(citations)} 篇")
        return {"references": references, "citations": citations}
    except Exception as e:
        print(f"❌ 网络错误: {e}")
        return {"references": [], "citations": []}


def ensure_paper_metadata(paper_item):
    """
    确保论文有摘要、作者：有 arxiv_id 则从 ArXiv 拉取，否则从 S2 用 paperId 拉取。
    不递归查找该论文的引用/被引用。
    """
    if paper_item.get("abstract") and paper_item.get("authors"):
        return paper_item
    if paper_item.get("arxiv_id"):
        meta = fetch_arxiv_paper(paper_item["arxiv_id"])
        if meta:
            paper_item["abstract"] = meta.get("abstract", "")
            paper_item["authors"] = meta.get("authors", [])
            paper_item["published_date"] = meta.get("published_date", "")
            paper_item["pdf_url"] = meta.get("pdf_url", "")
            return paper_item
    if paper_item.get("paper_id_s2"):
        meta = fetch_paper_from_semantic_scholar(paper_item["paper_id_s2"])
        if meta:
            paper_item["abstract"] = meta.get("abstract", "")
            paper_item["authors"] = meta.get("authors", [])
            paper_item["published_date"] = meta.get("published_date", "") or str(
                paper_item.get("year", "")
            )
            paper_item["pdf_url"] = meta.get("pdf_url", "")
            return paper_item
    paper_item.setdefault("abstract", "")
    paper_item.setdefault("authors", [])
    return paper_item


def batch_ensure_metadata(paper_list):
    """批量补全摘要、作者等，不递归查引用。"""
    print(f"\n[*] 补全 {len(paper_list)} 篇论文的摘要与作者...")
    for idx, paper in enumerate(paper_list):
        ensure_paper_metadata(paper)
        time.sleep(0.5)
    return paper_list


def extract_knowledge_with_llm(paper_info):
    """可选：LLM 深度抽取。未配置 API Key 则跳过。实体类型必须为 classes.json 中的类型。"""
    if not is_api_configured():
        return {"entities": [], "triples": []}
    print(f"[*] [LLM] 深度抽取: {paper_info['title'][:30]}...")
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    allowed_types = get_types_for_llm_prompt()
    system_prompt = f"""你是一个知识图谱专家。从论文摘要中提取实体和关系。
实体类型必须且仅能从以下类型中选择（来自 classes.json 规范）: {allowed_types}
关系类型: proposed_model, baseline_model, evaluated_on, uses_metric, cites, author_of
要求：triples 必须使用 "head" 和 "tail" 字段（不要用 subject/object）；head 和 tail 的值必须是实体名称（如论文标题、模型名、数据集名），不要用 E1、E2 等 ID。
严格输出 JSON: {{"entities": [{{"name": "...", "type": "..."}}], "triples": [{{"head": "...", "relation": "...", "tail": "..."}}]}}"""
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Title: {paper_info['title']}\nAbstract: {paper_info.get('abstract', '')}"},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"❌ LLM 错误: {e}")
        return {"entities": [], "triples": []}


def build_top_citations_kg(arxiv_id, top_n=5, run_llm=False):
    """
    主流程：根据 arxiv_id 和 top_n 构建知识图谱（不递归），输出 JSON 与 HTML。
    """
    print("\n" + "=" * 60)
    print("🚀 Top 引用知识图谱 (Top Citations KG)")
    print("=" * 60)
    print(f"   ArXiv ID: {arxiv_id}, Top N: {top_n}")

    seed = fetch_arxiv_paper(arxiv_id)
    if not seed:
        return False

    relation = fetch_related_papers_via_semantic_scholar(arxiv_id, top_n=top_n)
    refs = relation["references"]
    cites = relation["citations"]
    related = refs + cites
    batch_ensure_metadata(related)

    all_papers = [seed] + related
    seen_names = set()
    entities = []
    triples = []

    for p in all_papers:
        name = p.get("title") or ""
        if name and name not in seen_names:
            arxiv_id_val = p.get("arxiv_id") or p.get("id", "")
            entities.append({
                "name": name,
                "type": normalize_entity_type("AIPaper", allowed=ALLOWED_TYPES),
                "arxiv_id": arxiv_id_val,
            })
            seen_names.add(name)
    for p in all_papers:
        for a in p.get("authors", []):
            a = (a or "").strip()
            if a and a not in seen_names:
                entities.append({"name": a, "type": normalize_entity_type("Researcher", allowed=ALLOWED_TYPES)})
                seen_names.add(a)

    for p in all_papers:
        for a in p.get("authors", []):
            a = (a or "").strip()
            if a and p.get("title"):
                triples.append({"head": a, "relation": "author_of", "tail": p["title"]})
    for r in refs:
        if r.get("title") and seed.get("title"):
            triples.append({"head": seed["title"], "relation": "cites", "tail": r["title"]})
    for c in cites:
        if c.get("title") and seed.get("title"):
            triples.append({"head": c["title"], "relation": "cites", "tail": seed["title"]})

    if run_llm:
        for p in all_papers:
            llm_data = extract_knowledge_with_llm(p)
            # 实体 ID -> name，用于把三元组里的 E1/E2 解析成论文名、模型名等
            id_to_name = {}
            for e in llm_data.get("entities", []):
                n = e.get("name")
                if n:
                    if n not in seen_names:
                        raw_type = e.get("type", "Thesis")
                        entities.append({"name": n, "type": normalize_entity_type(raw_type, allowed=ALLOWED_TYPES)})
                        seen_names.add(n)
                    eid = e.get("id")
                    if eid:
                        id_to_name[eid] = n
                    id_to_name[n] = n  # 名字也映射到自己，方便 triples 里已用 name 的情况
            # 统一三元组格式并解析 ID：兼容 head/tail 与 subject/object，ID 转为 name
            for t in llm_data.get("triples", []):
                head = t.get("head") or t.get("subject")
                tail = t.get("tail") or t.get("object")
                if not head or not tail:
                    continue
                head = id_to_name.get(head, head)
                tail = id_to_name.get(tail, tail)
                triples.append({"head": head, "relation": t.get("relation", ""), "tail": tail})

    # 相关论文保留完整元数据（摘要、作者等），不递归查其引用/被引
    def _paper_meta(p):
        return {
            "title": p.get("title", ""),
            "arxiv_id": p.get("arxiv_id", ""),
            "abstract": p.get("abstract", ""),
            "authors": p.get("authors", []),
            "published_date": p.get("published_date", ""),
            "pdf_url": p.get("pdf_url", ""),
            "citation_count": p.get("citation_count"),
            "year": p.get("year"),
        }
    related_with_meta = [_paper_meta(p) for p in related]
    output_data = {
        "paper_metadata": seed,
        "related_papers_count": {"references": len(refs), "citations": len(cites)},
        "related_papers": related_with_meta,
        "top_n": top_n,
        "knowledge_graph": {"entities": entities, "triples": triples},
    }

    base_name = f"top_citations_kg_{arxiv_id}"
    json_path = f"{base_name}.json"
    html_path = f"{base_name}.html"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"\n✅ JSON 已保存: {json_path}")

    generate_html(json_path, html_path, output_data)
    return True


def generate_html(json_file, output_html_file, data=None):
    """
    根据 JSON 生成类似 visualize 的 ECharts 力导向图 HTML。
    """
    if data is None:
        if not os.path.exists(json_file):
            print(f"❌ 找不到文件: {json_file}")
            return
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    paper_meta = data.get("paper_metadata", {})
    kg = data.get("knowledge_graph", {})
    entities = kg.get("entities", [])
    triples = kg.get("triples", [])

    # 基于 classes.json 扩展：仅使用 schema 中存在的类型作为 categories
    raw_types = [e.get("type", "Thesis") for e in entities]
    type_list = get_categories_for_entities(raw_types)
    category_map = {t: i for i, t in enumerate(type_list)}
    categories = [{"name": t} for t in type_list]

    # 按 name 去重：同一人（同名）只保留一个节点，避免多篇论文作者出现重复节点
    name_to_entity = {}
    for e in entities:
        n = (e.get("name") or "").strip()
        if n and n not in name_to_entity:
            name_to_entity[n] = e
    echarts_nodes = []
    for n, e in name_to_entity.items():
        norm_type = normalize_entity_type(e.get("type", "Thesis"), allowed=ALLOWED_TYPES)
        sz = 50 if norm_type in ("Thesis", "Article", "CreativeWork") else 25
        echarts_nodes.append({
            "name": n,
            "category": category_map.get(norm_type, 0),
            "symbolSize": sz,
            "draggable": True,
            "value": norm_type,
        })
    seen = set(name_to_entity.keys())

    # 兼容 head/tail 与 subject/object；只保留两端都在节点集合中的边；head/tail 做 strip 与节点名一致
    node_names = seen
    echarts_links = []
    for t in triples:
        head = (t.get("head") or t.get("subject") or "").strip()
        tail = (t.get("tail") or t.get("object") or "").strip()
        if head and tail and head in node_names and tail in node_names:
            echarts_links.append({
                "source": head,
                "target": tail,
                "value": t.get("relation", ""),
            })

    # 优先使用同目录下的 echarts.min.js（避免 CDN 超时/被拦截），否则用 unpkg
    out_dir = os.path.dirname(os.path.abspath(output_html_file))
    echarts_local = os.path.join(out_dir, "echarts.min.js")
    script_src = "echarts.min.js" if os.path.exists(echarts_local) else "https://unpkg.com/echarts@5.4.3/dist/echarts.min.js"

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Top Citations KG - {paper_meta.get('title', '')[:50]}</title>
    <script src="{script_src}"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html, body {{ height: 100%; }}
        body {{ background: #f5f5f5; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }}
        #main {{ width: 100%; height: 100%; min-height: 400px; }}
        .panel {{
            position: absolute; background: white; border-radius: 8px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.1); padding: 20px; font-size: 14px; z-index: 999; max-width: 420px;
        }}
        .header {{ top: 20px; left: 20px; }}
        .stats {{ top: 20px; right: 20px; }}
        .header h2 {{ margin-bottom: 10px; color: #333; }}
        .header p {{ color: #666; margin: 5px 0; line-height: 1.5; }}
        .stat-item {{ margin: 8px 0; }}
        .stat-label {{ font-weight: bold; color: #333; }}
        .stat-value {{ color: #0066cc; }}
    </style>
</head>
<body>
    <div id="main"></div>
    <div class="panel header">
        <h2>📄 {paper_meta.get('title', 'Paper')}</h2>
        <p><strong>作者:</strong> {', '.join(paper_meta.get('authors', [])[:4])}</p>
        <p><strong>发表日期:</strong> {paper_meta.get('published_date', '')}</p>
        <p><strong>ArXiv ID:</strong> <code>{paper_meta.get('id', '')}</code></p>
    </div>
    <div class="panel stats">
        <div class="stat-item"><span class="stat-label">论文节点:</span> <span class="stat-value">{sum(1 for e in name_to_entity.values() if e.get('type') == 'AIPaper')}</span></div>
        <div class="stat-item"><span class="stat-label">研究者节点:</span> <span class="stat-value">{sum(1 for e in name_to_entity.values() if e.get('type') == 'Researcher')}</span></div>
        <div class="stat-item"><span class="stat-label">关系数:</span> <span class="stat-value">{len(triples)}</span></div>
        <div class="stat-item"><span class="stat-label">引用的论文 (top N):</span> <span class="stat-value">{data.get('related_papers_count', {}).get('references', 0)}</span></div>
        <div class="stat-item"><span class="stat-label">被引用的论文 (top N):</span> <span class="stat-value">{data.get('related_papers_count', {}).get('citations', 0)}</span></div>
    </div>
    <script type="text/javascript">
        function initChart() {{
            if (typeof echarts === 'undefined') {{
                document.getElementById('main').innerHTML = '<p style="padding:20px">无法加载 ECharts，请检查网络或 CDN。</p>';
                return;
            }}
            var chartDom = document.getElementById('main');
            var myChart = echarts.init(chartDom);
            var option = {{
                tooltip: {{ formatter: function(params) {{
                    if (params.dataType === 'node') return params.name + ' (' + (params.value || '') + ')';
                    return (params.source && params.source.name) + ' ' + (params.value || '') + ' ' + (params.target && params.target.name);
                }}}},
                legend: {{ data: {json.dumps([c['name'] for c in categories])} }},
                series: [{{
                    type: 'graph', layout: 'force',
                    data: {json.dumps(echarts_nodes)},
                    links: {json.dumps(echarts_links)},
                    categories: {json.dumps(categories)},
                    roam: true,
                    label: {{ show: true, position: 'right', formatter: '{{b}}' }},
                    edgeLabel: {{ fontSize: 11, formatter: '{{c}}' }},
                    edgeSymbol: ['none', 'arrow'], edgeSymbolSize: 10,
                    lineStyle: {{ color: 'source', curveness: 0.3 }},
                    force: {{ repulsion: 1500, edgeLength: 250 }},
                    emphasis: {{ focus: 'adjacency', lineStyle: {{ width: 4 }} }}
                }}]
            }};
            myChart.setOption(option);
            setTimeout(function() {{ myChart.resize(); }}, 100);
            window.addEventListener('resize', function() {{ myChart.resize(); }});
        }}
        if (document.readyState === 'loading') {{
            document.addEventListener('DOMContentLoaded', initChart);
        }} else {{
            initChart();
        }}
    </script>
</body>
</html>"""
    with open(output_html_file, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"✅ HTML 已生成: {os.path.abspath(output_html_file)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="输入论文 ArXiv ID 和数字 N，生成该论文引用/被引中 top N 的知识图谱 JSON 与 HTML"
    )
    parser.add_argument("arxiv_id", nargs="?", default="1706.03762", help="论文 ArXiv ID，例如 1706.03762")
    parser.add_argument("-n", "--top", type=int, default=5, help="引用/被引各取前 N 篇 (默认 5)")
    parser.add_argument("--llm", action="store_true", help="是否进行 LLM 深度抽取（需配置 API_KEY）")
    args = parser.parse_args()

    build_top_citations_kg(args.arxiv_id, top_n=args.top, run_llm=args.llm)
